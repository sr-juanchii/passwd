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

En esta versión la ejecución es **manual**: autorizada la rotación, una persona
cambia la contraseña en el activo y la registra aquí. Los agentes (1.4.0) y los
conectores (2.3.0) se enganchan al mismo ciclo sin cambiarlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.models import (
    ESTADOS_ROTACION_ABIERTOS,
    ROL_ADMIN,
    ROT_AUTORIZADA,
    ROT_CANCELADA,
    ROT_CERRADA,
    ROT_RECHAZADA,
    ROT_RES_CANCELADA,
    ROT_RES_MANUAL,
    ROT_SOLICITADA,
    ROT_TIPO_EMERGENCIA,
    ROT_TIPO_MANUAL,
    ROT_VERIF_NINGUNA,
    TIPOS_ROTACION,
    VIA_ROTACION_MANUAL,
    Credencial,
    HistorialCredencial,
    RotacionCredencial,
    Usuario,
    ahora_utc,
)
from app.security.crypto import cifrar

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
