"""Gobernanza de rotación de credenciales (v1.3.0).

Este módulo es el **único punto del sistema que escribe
``Credencial.password_cifrada``**. No es una convención de estilo: es el
control del que depende todo lo demás.

Hasta la 1.2.0 la contraseña de una credencial se podía cambiar por tres
caminos independientes —el formulario de la interfaz clásica, la API JSON del
frontend y la importación CSV—, cada uno con su propia copia de la lógica. Un
circuito de autorización colocado en uno solo de ellos no sería un control:
sería contabilidad, porque quien quisiera saltárselo solo tendría que entrar por
otra puerta. Y las reglas de detección de patrones quedarían ciegas justo ante
el comportamiento que deben detectar.

Por eso el ciclo completo vive aquí:

    SOLICITADA ──► AUTORIZADA ──► CERRADA
         │              │
         └─ rechazada ──┴─ cancelada

con **motivo obligatorio**, **regla de dos pares** (nadie autoriza su propia
solicitud) y **reautenticación con segundo factor** del autorizador. Cada paso
deja asiento en el libro mayor ``RotacionCredencial``, que no se purga nunca y
registra la antigüedad de la contraseña al solicitar, al autorizar y al rotar,
además de la desviación respecto a la fecha que marcaba la política. Ese dato
—«se rotó a los dos días» frente a «se rotó a los noventa exactos»— es lo que
permite ver un patrón raro sin recalcular nada después.

La ejecución tiene dos vías. **Manual**: autorizada la rotación, una persona
cambia la contraseña en el activo y la registra aquí. **Por agente** (v1.4.0):
autorizada la rotación de una credencial que rota por agente, se le despacha un
trabajo al agente de su activo, que la aplica, la verifica y confirma o revierte;
la confirmación vuelve aquí y es este módulo quien escribe la contraseña:

    AUTORIZADA ──despachar──► DESPACHADA ──resultado del agente──► CERRADA

Los conectores (2.3.0) se engancharán al mismo ciclo sin cambiarlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, notifications
from app.config import get_settings
from app.models import (
    AGENTE_ACTIVO,
    ESTADOS_ROTACION_ABIERTOS,
    ROL_ADMIN,
    ROT_AUTORIZADA,
    ROT_CANCELADA,
    ROT_CERRADA,
    ROT_DESPACHADA,
    ROT_RECHAZADA,
    ROT_RES_APLICADA,
    ROT_RES_CANCELADA,
    ROT_RES_FALLADA,
    ROT_RES_MANUAL,
    ROT_RES_REVERTIDA,
    ROT_SOLICITADA,
    ROT_TIPO_EMERGENCIA,
    ROT_TIPO_MANUAL,
    ROT_VERIF_LOCAL,
    ROT_VERIF_NINGUNA,
    TIPOS_ROTACION,
    TRABAJO_APLICADO,
    TRABAJO_CANCELADO,
    TRABAJO_ENTREGADO,
    TRABAJO_EXPIRADO,
    TRABAJO_FALLADO,
    TRABAJO_PENDIENTE,
    TRABAJO_REVERTIDO,
    VIA_ROTACION_AGENTE,
    VIA_ROTACION_MANUAL,
    Agente,
    Credencial,
    HistorialCredencial,
    RotacionCredencial,
    TrabajoRotacion,
    Usuario,
    ahora_utc,
)
from app.security.crypto import cifrar, descifrar
from app.security.passwords import generar_password

# Longitud mínima del motivo. No es burocracia: «rotación» no dice nada dentro
# de seis meses, cuando alguien revise por qué esta contraseña cambió a los dos
# días de la anterior.
MOTIVO_MIN = 10
MOTIVO_REFORZADO_MIN = 30
MOTIVO_MAX = 2000


class ErrorRotacion(Exception):
    """Regla de gobernanza incumplida. ``codigo`` es el HTTP que le corresponde."""

    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# ---------------------------------------------------------------------------
# Política: intervalo, fecha programada y antigüedad
# ---------------------------------------------------------------------------


def intervalo_dias() -> int:
    """Intervalo de política, en días.

    Es el mismo ``rotation_max_days`` que ya rige las alertas de antigüedad: un
    segundo ajuste con el mismo significado solo habría creado dos verdades.
    """
    return max(get_settings().rotation_max_days, 1)


def fecha_programada(credencial: Credencial) -> datetime:
    """Fecha en la que la política pide rotar esta credencial."""
    return credencial.password_rotada_en + timedelta(days=intervalo_dias())


def umbral_temprana() -> int:
    """Días por debajo de los cuales una rotación se considera temprana."""
    pct = min(max(get_settings().rotacion_temprana_pct, 1), 100)
    return max(intervalo_dias() * pct // 100, 1)


def es_temprana(credencial: Credencial) -> bool:
    return credencial.dias_sin_rotar < umbral_temprana()


# ---------------------------------------------------------------------------
# Escritura de contraseñas — el punto único
# ---------------------------------------------------------------------------


def podar_historial(db: Session, credencial_id: int) -> None:
    """Conserva solo las últimas N contraseñas anteriores de una credencial."""
    maximo = get_settings().password_history_max
    entradas = db.scalars(
        select(HistorialCredencial)
        .where(HistorialCredencial.credencial_id == credencial_id)
        .order_by(HistorialCredencial.rotada_en.desc(), HistorialCredencial.id.desc())
    ).all()
    for sobrante in entradas[maximo:]:
        db.delete(sobrante)


def nueva_credencial(
    db: Session,
    *,
    password: str,
    usuario_acceso: str,
    servicio: str = "SSH",
    puerto: int | None = None,
    descripcion: str = "",
    usada_por: str = "",
    creado_por_id: int | None = None,
    servidor_fisico_id: int | None = None,
    hipervisor_id: int | None = None,
    maquina_virtual_id: int | None = None,
    dispositivo_red_id: int | None = None,
) -> Credencial:
    """Da de **alta** una credencial con su contraseña ya cifrada.

    Un alta no es una rotación: no hay contraseña anterior que archivar ni
    desviación que medir, de modo que **no genera asiento en el libro mayor**.
    Pasa por el servicio igualmente para que ``password_rotada_en`` y
    ``via_rotacion`` queden coherentes desde el primer día de vida de la
    credencial, y para que ningún controlador necesite tocar el campo cifrado.
    """
    credencial = Credencial(
        usuario_acceso=usuario_acceso,
        password_cifrada=cifrar(password),
        servicio=servicio or "SSH",
        puerto=puerto,
        descripcion=descripcion,
        usada_por=usada_por,
        via_rotacion=VIA_ROTACION_MANUAL,
        creado_por_id=creado_por_id,
        password_rotada_en=ahora_utc(),
        servidor_fisico_id=servidor_fisico_id,
        hipervisor_id=hipervisor_id,
        maquina_virtual_id=maquina_virtual_id,
        dispositivo_red_id=dispositivo_red_id,
    )
    db.add(credencial)
    return credencial


def _escribir_password(db: Session, credencial: Credencial, password: str, usuario_id: int | None) -> None:
    """Sustituye la contraseña archivando la anterior. Privado a propósito."""
    db.add(HistorialCredencial(
        credencial_id=credencial.id,
        password_cifrada=credencial.password_cifrada,
        rotada_por_id=usuario_id,
    ))
    credencial.password_cifrada = cifrar(password)
    credencial.password_rotada_en = ahora_utc()
    podar_historial(db, credencial.id)


# ---------------------------------------------------------------------------
# Consultas del ciclo
# ---------------------------------------------------------------------------


def solicitud_abierta(db: Session, credencial_id: int) -> RotacionCredencial | None:
    """Solicitud viva de una credencial, si la hay. Solo puede haber una."""
    return db.scalar(
        select(RotacionCredencial)
        .where(RotacionCredencial.credencial_id == credencial_id,
               RotacionCredencial.estado.in_(ESTADOS_ROTACION_ABIERTOS))
        .order_by(RotacionCredencial.id.desc())
    )


def autorizacion_vigente(db: Session, credencial_id: int) -> RotacionCredencial | None:
    """Rotación autorizada y pendiente de ejecutar para esta credencial."""
    return db.scalar(
        select(RotacionCredencial)
        .where(RotacionCredencial.credencial_id == credencial_id,
               RotacionCredencial.estado == ROT_AUTORIZADA)
        .order_by(RotacionCredencial.id.desc())
    )


# La regla de dos pares necesita, como mínimo, dos administradores activos. Con
# uno solo no es que el control sea más débil: es que no se puede aplicar, y
# toda rotación acaba cayendo por la vía de emergencia marcada.
MIN_ADMINISTRADORES = 2


def administradores_activos(db: Session) -> int:
    return db.scalar(
        select(func.count(Usuario.id)).where(Usuario.rol == ROL_ADMIN, Usuario.activo.is_(True))
    ) or 0


def dos_pares_posible(db: Session) -> bool:
    """¿Hay gente suficiente para que la regla de dos pares signifique algo?"""
    return administradores_activos(db) >= MIN_ADMINISTRADORES


def pendientes_de_autorizar(db: Session) -> list[RotacionCredencial]:
    return list(db.scalars(
        select(RotacionCredencial)
        .where(RotacionCredencial.estado == ROT_SOLICITADA)
        .order_by(RotacionCredencial.solicitado_en)
    ).all())


def pendientes_de_ejecutar(db: Session) -> list[RotacionCredencial]:
    return list(db.scalars(
        select(RotacionCredencial)
        .where(RotacionCredencial.estado == ROT_AUTORIZADA)
        .order_by(RotacionCredencial.autorizado_en)
    ).all())


def revisiones_pendientes(db: Session) -> list[RotacionCredencial]:
    """Emergencias ejecutadas sin segundo par que nadie ha revisado todavía."""
    return list(db.scalars(
        select(RotacionCredencial)
        .where(RotacionCredencial.emergencia_sin_segundo_par.is_(True),
               RotacionCredencial.revisada_en.is_(None))
        .order_by(RotacionCredencial.solicitado_en)
    ).all())


def linea_de_tiempo(db: Session, credencial_id: int, limite: int = 50) -> list[RotacionCredencial]:
    """Historia de gobernanza de una credencial, de lo más reciente a lo más antiguo."""
    return list(db.scalars(
        select(RotacionCredencial)
        .where(RotacionCredencial.credencial_id == credencial_id)
        .order_by(RotacionCredencial.solicitado_en.desc(), RotacionCredencial.id.desc())
        .limit(limite)
    ).all())


# ---------------------------------------------------------------------------
# El ciclo: solicitar → autorizar → registrar
# ---------------------------------------------------------------------------


def _validar_motivo(motivo: str, *, reforzado: bool) -> str:
    limpio = (motivo or "").strip()
    minimo = MOTIVO_REFORZADO_MIN if reforzado else MOTIVO_MIN
    if len(limpio) < minimo:
        if reforzado:
            raise ErrorRotacion(
                "Una rotación temprana o de emergencia exige un motivo detallado "
                f"(al menos {minimo} caracteres): explique qué la hace necesaria ahora.",
            )
        raise ErrorRotacion(
            f"El motivo es obligatorio y debe tener al menos {minimo} caracteres.",
        )
    return limpio[:MOTIVO_MAX]


def solicitar(
    db: Session,
    *,
    credencial: Credencial,
    usuario: Usuario,
    motivo: str,
    tipo: str = ROT_TIPO_MANUAL,
    request: Request | None = None,
) -> RotacionCredencial:
    """Abre el ciclo. No cambia nada todavía: solo deja constancia de la petición."""
    if tipo not in TIPOS_ROTACION:
        raise ErrorRotacion(f"Tipo de rotación desconocido: {tipo}.")
    if solicitud_abierta(db, credencial.id) is not None:
        raise ErrorRotacion(
            "Esta credencial ya tiene una solicitud de rotación en curso. "
            "Resuélvala o cancélela antes de abrir otra.", codigo=409,
        )
    temprana = es_temprana(credencial)
    motivo_limpio = _validar_motivo(motivo, reforzado=temprana or tipo == ROT_TIPO_EMERGENCIA)

    rotacion = RotacionCredencial(
        credencial_id=credencial.id,
        activo_nombre=credencial.nombre_activo,
        usuario_acceso=credencial.usuario_acceso,
        servicio=credencial.servicio,
        estado=ROT_SOLICITADA,
        tipo=tipo,
        solicitado_por_id=usuario.id,
        solicitado_por_username=usuario.username,
        solicitado_en=ahora_utc(),
        motivo=motivo_limpio,
        dias_al_solicitar=credencial.dias_sin_rotar,
        temprana=temprana,
        fecha_programada=fecha_programada(credencial),
        via=credencial.via_rotacion,
    )
    db.add(rotacion)
    db.flush()
    audit.registrar(
        db, audit.ROTACION_SOLICITADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} — tipo {tipo}, "
                f"{credencial.dias_sin_rotar} día(s) sin rotar"
                + (" — TEMPRANA" if temprana else ""),
    )
    return rotacion


def _dentro_de_ventana_emergencia(rotacion: RotacionCredencial) -> bool:
    ventana = max(get_settings().rotacion_emergencia_ventana_min, 1)
    return ahora_utc() <= rotacion.solicitado_en + timedelta(minutes=ventana)


def autorizar(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    usuario: Usuario,
    request: Request | None = None,
) -> RotacionCredencial:
    """Autoriza una solicitud. **La reautenticación debe haberse hecho antes.**

    La regla de dos pares es el control central: nadie autoriza lo que pidió.
    Tiene una única salida, y es ruidosa: una solicitud de **emergencia**, dentro
    de una ventana corta, puede autorizarla su propio solicitante si es
    administrador. Queda marcada de forma imborrable y obliga a que otro
    administrador la revise después.

    Esa salida existe porque la alternativa es peor. Con un solo administrador
    disponible —instalación pequeña, madrugada, vacaciones— la regla estricta no
    detiene la rotación: la empuja fuera del sistema, donde no hay motivo, ni
    asiento, ni manera de verla. Mejor instrumentada y ruidosa que invisible.
    """
    if rotacion.estado != ROT_SOLICITADA:
        raise ErrorRotacion(
            f"Solo se puede autorizar una solicitud en estado «{ROT_SOLICITADA}»; "
            f"esta está en «{rotacion.estado}».", codigo=409,
        )
    if usuario.rol != ROL_ADMIN:
        raise ErrorRotacion("Solo un administrador puede autorizar una rotación.", codigo=403)

    sin_segundo_par = False
    if rotacion.solicitado_por_id == usuario.id:
        if rotacion.tipo != ROT_TIPO_EMERGENCIA:
            raise ErrorRotacion(
                "No puede autorizar su propia solicitud. La rotación exige dos personas: "
                "pida a otro administrador que la autorice.", codigo=403,
            )
        if not _dentro_de_ventana_emergencia(rotacion):
            ventana = get_settings().rotacion_emergencia_ventana_min
            raise ErrorRotacion(
                f"La ventana de emergencia ({ventana} min desde la solicitud) ya venció. "
                "Vuelve a aplicarse la regla de dos personas: otro administrador debe "
                "autorizarla.", codigo=403,
            )
        sin_segundo_par = True

    ahora = ahora_utc()
    rotacion.estado = ROT_AUTORIZADA
    rotacion.autorizado_por_id = usuario.id
    rotacion.autorizado_por_username = usuario.username
    rotacion.autorizado_en = ahora
    rotacion.reautenticado = True
    rotacion.emergencia_sin_segundo_par = sin_segundo_par
    credencial = rotacion.credencial
    if credencial is not None:
        rotacion.dias_al_autorizar = credencial.dias_sin_rotar

    audit.registrar(
        db, audit.ROTACION_AUTORIZADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{rotacion.usuario_acceso}@{rotacion.activo_nombre} — solicitada por "
                f"{rotacion.solicitado_por_username}"
                + (" — EMERGENCIA SIN SEGUNDO PAR" if sin_segundo_par else ""),
    )
    if sin_segundo_par:
        audit.registrar(
            db, audit.ROTACION_EMERGENCIA_SIN_PAR, request=request, usuario=usuario,
            objeto_tipo="rotacion", objeto_id=rotacion.id,
            detalle=f"Autorización propia en vía de emergencia — motivo: {rotacion.motivo[:300]}",
        )
    if credencial is not None and credencial.via_rotacion == VIA_ROTACION_AGENTE:
        _intentar_despacho(db, rotacion, usuario, request)
    return rotacion


def rechazar(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    usuario: Usuario,
    motivo: str,
    request: Request | None = None,
) -> RotacionCredencial:
    """Cierra la solicitud sin rotar. Rechazar también es una decisión auditable."""
    if rotacion.estado != ROT_SOLICITADA:
        raise ErrorRotacion(
            f"Solo se puede rechazar una solicitud pendiente; esta está en "
            f"«{rotacion.estado}».", codigo=409,
        )
    if usuario.rol != ROL_ADMIN:
        raise ErrorRotacion("Solo un administrador puede rechazar una rotación.", codigo=403)
    limpio = (motivo or "").strip()
    if len(limpio) < MOTIVO_MIN:
        raise ErrorRotacion(
            f"Indique por qué rechaza la solicitud (al menos {MOTIVO_MIN} caracteres).",
        )

    rotacion.estado = ROT_RECHAZADA
    rotacion.rechazado_por_id = usuario.id
    rotacion.rechazado_en = ahora_utc()
    rotacion.motivo_rechazo = limpio[:MOTIVO_MAX]
    audit.registrar(
        db, audit.ROTACION_RECHAZADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{rotacion.usuario_acceso}@{rotacion.activo_nombre} — {limpio[:300]}",
    )
    return rotacion


def cancelar(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    usuario: Usuario,
    request: Request | None = None,
) -> RotacionCredencial:
    """Retira una solicitud propia (o cualquiera, si es administrador)."""
    if not rotacion.abierta:
        raise ErrorRotacion(
            f"La solicitud ya está en «{rotacion.estado}» y no se puede cancelar.", codigo=409,
        )
    propia = rotacion.solicitado_por_id == usuario.id
    if not propia and usuario.rol != ROL_ADMIN:
        raise ErrorRotacion("Solo puede cancelar sus propias solicitudes.", codigo=403)
    if rotacion.estado == ROT_DESPACHADA:
        trabajo = trabajo_de(db, rotacion)
        if trabajo is not None and trabajo.estado == TRABAJO_ENTREGADO:
            raise ErrorRotacion(
                "El agente ya recogió este trabajo y puede estar aplicándolo: no se puede "
                "cancelar. Espere a su resultado.", codigo=409,
            )
        if trabajo is not None:
            _cerrar_trabajo(trabajo, TRABAJO_CANCELADO, "Cancelado junto con la solicitud")
            audit.registrar(db, audit.TRABAJO_CANCELADO, request=request, usuario=usuario,
                            objeto_tipo="trabajo", objeto_id=trabajo.id,
                            detalle=f"Solicitud {rotacion.id} cancelada antes de la entrega")

    rotacion.estado = ROT_CANCELADA
    rotacion.resultado = ROT_RES_CANCELADA
    rotacion.cancelado_por_id = usuario.id
    rotacion.cancelado_en = ahora_utc()
    audit.registrar(
        db, audit.ROTACION_CANCELADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{rotacion.usuario_acceso}@{rotacion.activo_nombre}",
    )
    return rotacion


def registrar_rotacion_manual(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    password: str,
    usuario: Usuario,
    request: Request | None = None,
) -> RotacionCredencial:
    """Cierra el ciclo: la persona cambió la contraseña en el activo y la registra.

    Es el **único** camino por el que una contraseña del inventario cambia en
    esta versión, y exige una autorización vigente: sin ella no hay escritura.

    La antigüedad se mide **antes** de escribir, que es lo que da sentido al
    dato: ``dias_al_rotar`` dice cuánto duró realmente la contraseña anterior y
    ``desvio_dias`` cuánto se adelantó (negativo) o se retrasó respecto a lo que
    marcaba la política.
    """
    if rotacion.estado != ROT_AUTORIZADA:
        raise ErrorRotacion(
            "No hay una autorización vigente para esta rotación. El ciclo es "
            "solicitar → autorizar → registrar.", codigo=409,
        )
    credencial = rotacion.credencial
    if credencial is None:
        raise ErrorRotacion("La credencial de esta rotación ya no existe.", codigo=404)
    if not password:
        raise ErrorRotacion("Indique la contraseña nueva que quedó aplicada en el activo.")

    dias = credencial.dias_sin_rotar
    _escribir_password(db, credencial, password, usuario.id)

    ahora = ahora_utc()
    rotacion.estado = ROT_CERRADA
    rotacion.resultado = ROT_RES_MANUAL
    rotacion.via = VIA_ROTACION_MANUAL
    rotacion.verificacion = ROT_VERIF_NINGUNA
    rotacion.ejecutado_en = ahora
    rotacion.confirmado_en = ahora
    rotacion.dias_al_rotar = dias
    rotacion.desvio_dias = dias - intervalo_dias()

    audit.registrar(
        db, audit.ROTACION_MANUAL_REGISTRADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} — rotada a los "
                f"{dias} día(s) (desvío {rotacion.desvio_dias:+d}), autorizada por "
                f"{rotacion.autorizado_por_username}",
    )
    audit.registrar(
        db, audit.ROTACION_APLICADA, request=request, usuario=usuario,
        objeto_tipo="credencial", objeto_id=credencial.id,
        detalle=f"Contraseña rotada bajo la solicitud {rotacion.id}",
    )
    return rotacion


MENSAJE_SIN_AUTORIZACION = (
    "Cambiar la contraseña de una credencial exige una rotación autorizada. "
    "Solicite la rotación indicando el motivo, espere a que otro administrador la "
    "autorice y registre entonces la contraseña que quedó aplicada en el activo."
)


def exigir_autorizacion(db: Session, credencial: Credencial) -> RotacionCredencial:
    """Devuelve la autorización vigente de la credencial o explica que falta.

    Es el punto por el que los formularios de credencial —el de la interfaz
    clásica y el de la API JSON— entran al ciclo. Se comprueba **antes** de tocar
    ningún campo, para que un intento sin autorización no deje cambios a medias.
    """
    rotacion = autorizacion_vigente(db, credencial.id)
    if rotacion is None:
        raise ErrorRotacion(MENSAJE_SIN_AUTORIZACION, codigo=409)
    return rotacion


def marcar_revisada(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    usuario: Usuario,
    nota: str = "",
    request: Request | None = None,
) -> RotacionCredencial:
    """Cierra la revisión obligatoria de una emergencia autorizada sin segundo par.

    La revisa **otro** administrador: si pudiera cerrarla quien la autorizó, la
    marca no obligaría a nada.
    """
    if not rotacion.emergencia_sin_segundo_par:
        raise ErrorRotacion("Esta rotación no requiere revisión.", codigo=409)
    if rotacion.revisada_en is not None:
        raise ErrorRotacion("Esta emergencia ya fue revisada.", codigo=409)
    if usuario.rol != ROL_ADMIN:
        raise ErrorRotacion("Solo un administrador puede revisar una emergencia.", codigo=403)
    if rotacion.autorizado_por_id == usuario.id:
        raise ErrorRotacion(
            "La revisión la hace otro administrador: quien autorizó la emergencia no "
            "puede darla por revisada.", codigo=403,
        )

    rotacion.revisada_por_id = usuario.id
    rotacion.revisada_en = ahora_utc()
    rotacion.nota_revision = (nota or "").strip()[:MOTIVO_MAX]
    audit.registrar(
        db, audit.ROTACION_EMERGENCIA_REVISADA, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"Revisión de la emergencia autorizada por {rotacion.autorizado_por_username}",
    )
    return rotacion


# ---------------------------------------------------------------------------
# Ejecución por agente (v1.4.0) — docs/plan-rotacion-agentes.md §2.2 y §3.2
# ---------------------------------------------------------------------------
#
# El agente nunca decide nada: recibe un trabajo que ya está AUTORIZADO, lo
# aplica, lo verifica y confirma o revierte. La contraseña nueva la genera el
# backend y no pasa a la credencial hasta que el agente confirma «aplicado»;
# entonces la escribe ``_escribir_password``, como en la vía manual.

# Tras la ventana, cuánto se espera al resultado de un trabajo ya entregado
# antes de darlo por «sin confirmar». El agente pudo aplicarlo justo al final
# de la ventana y estar confirmando: no es motivo de alarma inmediata.
MARGEN_CONFIRMACION = timedelta(minutes=15)
MARCA_SIN_CONFIRMAR = (
    "Sin confirmación del agente: la contraseña pudo cambiarse en el activo o no. "
    "Compruébelo y resuélvalo a mano."
)
RESULTADOS_AGENTE = {
    TRABAJO_APLICADO: ROT_RES_APLICADA,
    TRABAJO_REVERTIDO: ROT_RES_REVERTIDA,
    TRABAJO_FALLADO: ROT_RES_FALLADA,
}
_LARGO_DETALLE = 2000


def trabajo_activo_de(db: Session, agente: Agente) -> TrabajoRotacion | None:
    """El trabajo que ocupa el único turno del agente, si lo hay."""
    return db.scalar(select(TrabajoRotacion).where(TrabajoRotacion.activo_agente_id == agente.id))


def trabajo_de(db: Session, rotacion: RotacionCredencial) -> TrabajoRotacion | None:
    """El último trabajo despachado para un asiento del libro mayor."""
    return db.scalar(
        select(TrabajoRotacion).where(TrabajoRotacion.rotacion_id == rotacion.id)
        .order_by(TrabajoRotacion.id.desc())
    )


PREFIJO_NO_DESPACHADA = "Autorizada pero no despachada: "


def motivo_no_despacho(db: Session, rotacion: RotacionCredencial) -> str:
    """Por qué una rotación autorizada por agente no está en manos del agente.

    Lo más reciente manda: si después del último intento de despacho fallido
    hubo un trabajo y venció sin recogerse, es eso; si no, el motivo que quedó
    en la bitácora al intentar despacharla (anti-thrash, agente caducado…).
    Vacío si no se sabe.
    """
    from app.models import RegistroAuditoria

    evento = db.scalars(
        select(RegistroAuditoria)
        .where(RegistroAuditoria.accion == audit.ROTACION_NO_DESPACHADA,
               RegistroAuditoria.objeto_tipo == "rotacion",
               RegistroAuditoria.objeto_id == str(rotacion.id))
        .order_by(RegistroAuditoria.id.desc())
    ).first()
    trabajo = trabajo_de(db, rotacion)
    if trabajo is not None and trabajo.estado == TRABAJO_EXPIRADO and (
            evento is None or trabajo.creado_en >= evento.fecha):
        return "El trabajo venció sin que el agente lo recogiera (¿estaba parado o sin red?)."
    if evento is not None:
        return evento.detalle.removeprefix(PREFIJO_NO_DESPACHADA)
    return ""


def _cerrar_trabajo(trabajo: TrabajoRotacion, estado: str, detalle: str = "") -> None:
    """Cierra un trabajo: libera el turno del agente y **purga sus secretos**."""
    trabajo.estado = estado
    trabajo.activo_agente_id = None
    trabajo.nueva_cifrada = None
    trabajo.actual_cifrada = None
    trabajo.confirmado_en = ahora_utc()
    if detalle:
        trabajo.detalle_error = detalle[:_LARGO_DETALLE]


def despachar(
    db: Session,
    *,
    rotacion: RotacionCredencial,
    usuario: Usuario | None = None,
    request: Request | None = None,
) -> TrabajoRotacion:
    """Crea el trabajo del agente para una rotación **autorizada**.

    Invariante 1 del plan (§3.2): no hay despacho sin ``AUTORIZADA``. El agente
    tiene que ser el vigente **del activo de la credencial**, estar enrolado con
    identidad válida, admitir rotaciones y tener una versión aceptada.
    """
    from app.servicios import agentes

    if not agentes.habilitados():
        raise ErrorRotacion("Los agentes de rotación están desactivados.", codigo=409)
    if rotacion.estado != ROT_AUTORIZADA:
        raise ErrorRotacion(
            "Solo se despacha a un agente una rotación AUTORIZADA; esta está en "
            f"«{rotacion.estado}».", codigo=409,
        )
    credencial = rotacion.credencial
    if credencial is None:
        raise ErrorRotacion("La credencial de esta rotación ya no existe.", codigo=404)
    if credencial.via_rotacion != VIA_ROTACION_AGENTE:
        raise ErrorRotacion("Esta credencial no rota por agente.", codigo=409)

    agente = agentes.agente_vigente_de(db, *agentes.activo_de_credencial(credencial))
    if agente is None or agente.estado != AGENTE_ACTIVO:
        raise ErrorRotacion("El activo de esta credencial no tiene un agente enrolado.", codigo=409)
    if agentes.cobertura(agente) == agentes.COBERTURA_CADUCADO:
        raise ErrorRotacion(
            f"La identidad del agente {agente.nombre} caducó: vuelva a enrolarlo.", codigo=409,
        )
    if not agente.rotacion_habilitada:
        raise ErrorRotacion(f"El agente {agente.nombre} tiene las rotaciones desactivadas.", codigo=409)
    if not agentes.version_admitida(db, agente)[0]:
        raise ErrorRotacion(
            f"El agente {agente.nombre} (versión {agente.version_agente or '?'}) está por debajo "
            "de la versión mínima: actualícelo.", codigo=409,
        )
    if trabajo_activo_de(db, agente) is not None:
        raise ErrorRotacion(f"El agente {agente.nombre} tiene otro trabajo en curso.", codigo=409)

    horas = max(get_settings().rotacion_anti_thrash_horas, 0)
    ultima = ultima_rotacion_efectiva(db, credencial)
    desde_ultima = ahora_utc() - ultima if ultima is not None else None
    if desde_ultima is not None and desde_ultima < timedelta(hours=horas):
        if rotacion.tipo != ROT_TIPO_EMERGENCIA:
            raise ErrorRotacion(
                f"Esta credencial se rotó hace menos de {horas} h. Para volver a rotarla tan "
                "pronto por agente hace falta una solicitud de emergencia.", codigo=409,
            )
        # La única excepción (§4.1, prohibición 13): ruidosa y registrada. En el
        # libro mayor queda por el tipo y la antigüedad al rotar.
        audit.registrar(
            db, audit.ROTACION_ANTI_THRASH_SALTADO, request=request, usuario=usuario,
            username="" if usuario else "sistema", objeto_tipo="rotacion", objeto_id=rotacion.id,
            detalle=f"Emergencia: rotada hace {int(desde_ultima.total_seconds() // 3600)} h, "
                    f"por debajo del mínimo de {horas} h",
        )

    ahora = ahora_utc()
    ventana = timedelta(minutes=max(get_settings().rotacion_ventana_job_min, 1))
    trabajo = TrabajoRotacion(
        agente_id=agente.id,
        credencial_id=credencial.id,
        rotacion_id=rotacion.id,
        activo_agente_id=agente.id,
        estado=TRABAJO_PENDIENTE,
        # En reposo, el Fernet del backend (H14): al confirmar hay que escribirla.
        nueva_cifrada=cifrar(generar_password(credencial.usuario_acceso)),
        actual_cifrada=credencial.password_cifrada,
        clave_huella=agente.clave_huella,
        ventana_expira_en=ahora + ventana,
        disparado_por_id=usuario.id if usuario else None,
    )
    db.add(trabajo)
    rotacion.estado = ROT_DESPACHADA
    rotacion.via = VIA_ROTACION_AGENTE
    rotacion.agente_id = agente.id
    rotacion.agente_nombre = agente.nombre
    rotacion.clave_agente_huella = agente.clave_huella
    db.flush()
    audit.registrar(
        db, audit.ROTACION_DESPACHADA, request=request, usuario=usuario,
        username="" if usuario else "sistema", objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} → agente {agente.nombre}, "
                f"trabajo {trabajo.id}, válido hasta {trabajo.ventana_expira_en:%Y-%m-%d %H:%M} UTC",
    )
    return trabajo


def ultima_rotacion_efectiva(db: Session, credencial: Credencial) -> datetime | None:
    """Cuándo cambió por última vez de verdad la contraseña, según el libro mayor.

    Es lo que mide el anti-thrash: cortar un bucle de ROTACIONES. No vale
    ``password_rotada_en``, que también se fija al dar de alta la credencial o
    al importarla: con ella, una credencial recién creada no se podía rotar por
    agente en 24 h sin una emergencia (hallado en calidad con la 1.4.0-rc.2).
    Cuenta toda rotación cerrada que cambió la contraseña, por agente
    (aplicada) o a mano (registrada), sea cual sea la vía.
    """
    return db.scalar(
        select(func.max(func.coalesce(RotacionCredencial.confirmado_en, RotacionCredencial.ejecutado_en)))
        .where(RotacionCredencial.credencial_id == credencial.id,
               RotacionCredencial.estado == ROT_CERRADA,
               RotacionCredencial.resultado.in_((ROT_RES_APLICADA, ROT_RES_MANUAL))))


def _intentar_despacho(db: Session, rotacion: RotacionCredencial, usuario: Usuario,
                       request: Request | None) -> None:
    """Despacha tras autorizar; si no se puede, la autorización **se mantiene**.

    Que el agente esté sin contacto o el interruptor apagado no invalida la
    decisión de dos personas: se registra por qué no salió el trabajo, y se
    despacha cuando se corrija o se registra la rotación a mano.
    """
    try:
        despachar(db, rotacion=rotacion, usuario=usuario, request=request)
    except ErrorRotacion as exc:
        audit.registrar(
            db, audit.ROTACION_NO_DESPACHADA, request=request, usuario=usuario,
            objeto_tipo="rotacion", objeto_id=rotacion.id, exito=False,
            detalle=f"{PREFIJO_NO_DESPACHADA}{exc.mensaje}",
        )


def entregar(
    db: Session, *, agente: Agente, request: Request | None = None,
) -> tuple[TrabajoRotacion, dict] | None:
    """El trabajo del agente, **sellado** a su clave, o ``None`` si no hay ninguno.

    Un trabajo entregado se vuelve a entregar al mismo agente mientras su
    ventana siga abierta (``intentos`` lo cuenta): si el agente se reinició tras
    recibirlo, su journal decide con el ``trabajo_id`` si ya lo había empezado.
    """
    from app.servicios import agentes, cifrado_agente

    expirar_trabajos(db, agente_id=agente.id)
    if not agentes.version_admitida(db, agente)[0]:
        return None
    trabajo = trabajo_activo_de(db, agente)
    if trabajo is None or trabajo.ventana_expira_en <= ahora_utc():
        return None

    primera = trabajo.estado == TRABAJO_PENDIENTE
    trabajo.estado = TRABAJO_ENTREGADO
    trabajo.intentos += 1
    if primera:
        trabajo.entregado_en = ahora_utc()
        trabajo.rotacion.ejecutado_en = trabajo.entregado_en
    sobre = cifrado_agente.sellar(agente.clave_publica, {
        "trabajo_id": trabajo.id,
        "tipo": "rotar_cuenta",
        "usuario": trabajo.credencial.usuario_acceso,
        "nueva": descifrar(trabajo.nueva_cifrada),     # type: ignore[arg-type]
        "actual": descifrar(trabajo.actual_cifrada),   # type: ignore[arg-type]
        "expira_en": trabajo.ventana_expira_en.isoformat(timespec="seconds"),
        # La única excepción al anti-thrash local del agente, igual que al del backend.
        "emergencia": trabajo.rotacion.tipo == ROT_TIPO_EMERGENCIA,
    })
    audit.registrar(
        db, audit.TRABAJO_ENTREGADO, request=request, username=agentes.sujeto(agente),
        objeto_tipo="trabajo", objeto_id=trabajo.id,
        detalle=f"Entrega {trabajo.intentos} de la rotación {trabajo.rotacion_id} "
                f"({trabajo.credencial.usuario_acceso})",
    )
    return trabajo, sobre


def registrar_resultado(
    db: Session,
    *,
    agente: Agente,
    trabajo_id: int,
    estado: str,
    verificacion: str = ROT_VERIF_LOCAL,
    detalle: str = "",
    request: Request | None = None,
) -> TrabajoRotacion:
    """Cierra un trabajo con lo que informa su agente. Un resultado por trabajo.

    ``aplicado`` escribe la contraseña nueva por ``_escribir_password`` —el
    mismo y único punto que la vía manual— y archiva la anterior. ``revertido``
    y ``fallado`` no la tocan: el activo quedó como estaba, y se avisa.
    """
    from app.servicios import agentes

    if estado not in RESULTADOS_AGENTE:
        raise ErrorRotacion(f"Resultado desconocido: {estado}.")
    if verificacion not in (ROT_VERIF_LOCAL, ROT_VERIF_NINGUNA):
        # Un agente verifica en el propio sistema; la remota la hace el backend (2.2.0).
        raise ErrorRotacion("Un agente solo puede declarar verificación local.")
    trabajo = db.get(TrabajoRotacion, trabajo_id)
    if trabajo is None:
        raise ErrorRotacion("No existe ese trabajo.", codigo=404)
    if trabajo.agente_id != agente.id:
        audit.registrar(
            db, audit.TRABAJO_RESULTADO_RECHAZADO, request=request, username=agentes.sujeto(agente),
            objeto_tipo="trabajo", objeto_id=trabajo_id, exito=False,
            detalle="Resultado de un trabajo de otro agente",
        )
        raise ErrorRotacion("Ese trabajo no es de este agente.", codigo=403)
    if trabajo.estado != TRABAJO_ENTREGADO:
        # Anti-replay: cada trabajo admite un único resultado, y solo tras entregarse.
        audit.registrar(
            db, audit.TRABAJO_RESULTADO_RECHAZADO, request=request, username=agentes.sujeto(agente),
            objeto_tipo="trabajo", objeto_id=trabajo_id, exito=False,
            detalle=f"Resultado «{estado}» para un trabajo en estado «{trabajo.estado}»",
        )
        raise ErrorRotacion(f"Este trabajo ya está en «{trabajo.estado}».", codigo=409)

    rotacion = trabajo.rotacion
    credencial = trabajo.credencial
    detalle = (detalle or "").strip()[:_LARGO_DETALLE]
    ahora = ahora_utc()
    dias = credencial.dias_sin_rotar
    if estado == TRABAJO_APLICADO:
        _escribir_password(db, credencial, descifrar(trabajo.nueva_cifrada), None)  # type: ignore[arg-type]
        rotacion.dias_al_rotar = dias
        rotacion.desvio_dias = dias - intervalo_dias()

    rotacion.estado = ROT_CERRADA
    rotacion.resultado = RESULTADOS_AGENTE[estado]
    rotacion.verificacion = verificacion if estado == TRABAJO_APLICADO else ROT_VERIF_NINGUNA
    rotacion.confirmado_en = ahora
    rotacion.detalle_error = detalle
    trabajo.verificacion = rotacion.verificacion
    _cerrar_trabajo(trabajo, estado, detalle)

    audit.registrar(
        db, audit.TRABAJO_RESULTADO, request=request, username=agentes.sujeto(agente),
        objeto_tipo="rotacion", objeto_id=rotacion.id, exito=estado == TRABAJO_APLICADO,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo}: {estado}"
                + (f" (verificación {rotacion.verificacion})" if estado == TRABAJO_APLICADO else "")
                + (f" — {detalle[:300]}" if detalle else ""),
    )
    if estado == TRABAJO_APLICADO:
        audit.registrar(
            db, audit.ROTACION_APLICADA, request=request, username=agentes.sujeto(agente),
            objeto_tipo="credencial", objeto_id=credencial.id,
            detalle=f"Contraseña rotada por el agente {agente.nombre} bajo la solicitud {rotacion.id}",
        )
    else:
        notifications.enviar_alerta(
            f"[passwd] Rotación {estado} en {credencial.nombre_activo}",
            f"El agente «{agente.nombre}» informa «{estado}» al rotar "
            f"{credencial.usuario_acceso}@{credencial.nombre_activo} (solicitud {rotacion.id}).\n\n"
            "La contraseña registrada NO ha cambiado. "
            + (f"Detalle del agente: {detalle[:500]}" if detalle else ""),
        )
    return trabajo


def expirar_trabajos(db: Session, *, agente_id: int | None = None) -> dict[str, int]:
    """Cierra lo que venció. Se llama al entregar, al consultar y en el mantenimiento.

    - **Pendiente** vencido: nadie lo recogió. Se purga y el asiento vuelve a
      ``AUTORIZADA``: la decisión de dos personas sigue en pie.
    - **Entregado** sin resultado pasada la ventana y un margen: el agente pudo
      cambiar la contraseña o no. No se purga nada —la nueva puede ser la que
      vale ahora en el activo— y se marca para que una persona lo resuelva.
      Nunca un estado indeterminado en silencio (§2.2, paso 5).
    """
    ahora = ahora_utc()
    consulta = select(TrabajoRotacion).where(TrabajoRotacion.activo_agente_id.is_not(None))
    if agente_id is not None:
        consulta = consulta.where(TrabajoRotacion.agente_id == agente_id)
    cuenta = {"expirados": 0, "sin_confirmar": 0}
    for trabajo in db.scalars(consulta).all():
        if trabajo.estado == TRABAJO_PENDIENTE and trabajo.ventana_expira_en <= ahora:
            _cerrar_trabajo(trabajo, TRABAJO_EXPIRADO, "El agente no lo recogió dentro de su ventana")
            if trabajo.rotacion.estado == ROT_DESPACHADA:
                trabajo.rotacion.estado = ROT_AUTORIZADA
            audit.registrar(
                db, audit.TRABAJO_EXPIRADO, username="sistema", objeto_tipo="trabajo",
                objeto_id=trabajo.id,
                detalle=f"Rotación {trabajo.rotacion_id} sin recoger: vuelve a quedar autorizada",
            )
            cuenta["expirados"] += 1
        elif (trabajo.estado == TRABAJO_ENTREGADO and not trabajo.detalle_error
              and trabajo.ventana_expira_en + MARGEN_CONFIRMACION <= ahora):
            _marcar_sin_confirmar(db, trabajo)
            cuenta["sin_confirmar"] += 1
    return cuenta


def sin_confirmar(trabajo: TrabajoRotacion) -> bool:
    """¿Este trabajo espera que una persona diga qué quedó en el activo?"""
    return trabajo.estado == TRABAJO_ENTREGADO and trabajo.detalle_error == MARCA_SIN_CONFIRMAR


def trabajos_sin_confirmar(db: Session) -> list[TrabajoRotacion]:
    """Entregados sin resultado que ya no cabe esperar: el agente calló o fue revocado."""
    return [
        t for t in db.scalars(select(TrabajoRotacion)
                              .where(TrabajoRotacion.estado == TRABAJO_ENTREGADO)).all()
        if sin_confirmar(t) or t.agente.revocado
    ]


def _marcar_sin_confirmar(db: Session, trabajo: TrabajoRotacion) -> None:
    trabajo.detalle_error = MARCA_SIN_CONFIRMAR
    credencial = trabajo.credencial
    audit.registrar(
        db, audit.TRABAJO_SIN_CONFIRMAR, username="sistema", objeto_tipo="trabajo",
        objeto_id=trabajo.id, exito=False,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo}: entregado al agente "
                f"{trabajo.agente.nombre} sin resultado",
    )
    notifications.enviar_alerta(
        f"[passwd] Rotación sin confirmar en {credencial.nombre_activo}",
        f"El agente «{trabajo.agente.nombre}» recogió la rotación de "
        f"{credencial.usuario_acceso}@{credencial.nombre_activo} y no ha informado del resultado.\n\n"
        "La contraseña pudo cambiar en el activo o no. Compruébelo y resuélvalo desde el panel: "
        "hasta entonces la credencial no admite otra rotación.",
    )


def resolver_sin_confirmar(
    db: Session,
    *,
    trabajo: TrabajoRotacion,
    aplicada: bool,
    usuario: Usuario,
    request: Request | None = None,
) -> TrabajoRotacion:
    """Una persona comprueba el activo y dice qué contraseña quedó.

    Solo para trabajos entregados que ya no van a confirmarse: marcados «sin
    confirmar» o de un agente revocado. Si quedó la nueva, se escribe por el
    punto único; si no, se descarta. En los dos casos se purgan los secretos.
    """
    if usuario.rol != ROL_ADMIN:
        raise ErrorRotacion("Solo un administrador puede resolver una rotación sin confirmar.", codigo=403)
    if trabajo.estado != TRABAJO_ENTREGADO:
        raise ErrorRotacion(f"Este trabajo ya está en «{trabajo.estado}».", codigo=409)
    if not (sin_confirmar(trabajo) or trabajo.agente.revocado):
        raise ErrorRotacion(
            "El agente aún puede confirmar este trabajo: espere a su resultado.", codigo=409,
        )
    rotacion = trabajo.rotacion
    credencial = trabajo.credencial
    dias = credencial.dias_sin_rotar
    if aplicada:
        _escribir_password(db, credencial, descifrar(trabajo.nueva_cifrada), usuario.id)  # type: ignore[arg-type]
        rotacion.dias_al_rotar = dias
        rotacion.desvio_dias = dias - intervalo_dias()
    explicacion = (f"Resuelto a mano por {usuario.username}: "
                   + ("la contraseña nueva SÍ quedó aplicada en el activo" if aplicada
                      else "la contraseña nueva NO quedó aplicada en el activo"))
    rotacion.estado = ROT_CERRADA
    rotacion.resultado = ROT_RES_APLICADA if aplicada else ROT_RES_FALLADA
    rotacion.verificacion = ROT_VERIF_NINGUNA  # lo comprobó una persona, no el sistema
    rotacion.confirmado_en = ahora_utc()
    rotacion.detalle_error = explicacion
    _cerrar_trabajo(trabajo, TRABAJO_APLICADO if aplicada else TRABAJO_FALLADO, explicacion)
    audit.registrar(
        db, audit.TRABAJO_RESUELTO, request=request, usuario=usuario,
        objeto_tipo="rotacion", objeto_id=rotacion.id,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo}: {explicacion}",
    )
    return trabajo


def al_revocar_agente(db: Session, agente: Agente, usuario: Usuario,
                      request: Request | None = None) -> None:
    """Trabajos de un agente que se revoca: sin estados fantasma.

    El pendiente se cancela y su asiento vuelve a ``AUTORIZADA``. El entregado
    queda «sin confirmar»: el agente pudo aplicarlo antes de perder la identidad,
    y ya no podrá decirlo.
    """
    trabajo = trabajo_activo_de(db, agente)
    if trabajo is None:
        return
    if trabajo.estado == TRABAJO_PENDIENTE:
        _cerrar_trabajo(trabajo, TRABAJO_CANCELADO, "Agente revocado antes de la entrega")
        if trabajo.rotacion.estado == ROT_DESPACHADA:
            trabajo.rotacion.estado = ROT_AUTORIZADA
        audit.registrar(db, audit.TRABAJO_CANCELADO, request=request, usuario=usuario,
                        objeto_tipo="trabajo", objeto_id=trabajo.id,
                        detalle=f"Agente {agente.nombre} revocado: la rotación vuelve a quedar autorizada")
    elif not trabajo.detalle_error:
        _marcar_sin_confirmar(db, trabajo)
