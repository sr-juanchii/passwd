"""Casos de uso de las credenciales del inventario.

Aquí viven las **reglas**: qué activo resuelve un tipo, quién puede ver una
credencial, quién puede revelarla, cuánto puede revelar antes de que el límite
anti-exfiltración lo frene y qué queda escrito en la bitácora. Los controladores
—``app/routes/credentials.py`` para la interfaz clásica y
``app/api_web/credentials.py`` para la API JSON— solo traducen HTTP ↔ servicio.

Antes de esta versión, la entrega de una contraseña en claro estaba escrita
**dos veces**, línea por línea, en esos dos controladores: mismo control de
acceso, mismo límite de tasa, misma auditoría, mantenidos en paralelo. Esa
duplicación no es un problema estético: es la que produjo el fallo de la 1.2.0,
donde una de las dos ramas entregaba a un operador los activos restringidos que
la otra sí filtraba. Un control que vive en un controlador solo protege a quien
entra por ese controlador.

La escritura de la contraseña **no** está aquí: pertenece a
``app/servicios/rotacion.py``, que es su punto único (§2.4 del plan de rotación).
Este módulo la invoca para el alta y para aplicar una rotación ya autorizada.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app import access, audit, avisos
from app.config import get_settings
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ROL_ANALISTA,
    Credencial,
    DispositivoRed,
    Hipervisor,
    HistorialCredencial,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
)
from app.notifications import enviar_alerta
from app.security import ratelimit
from app.security.crypto import descifrar
from app.servicios import rotacion as rotacion_svc
from app.servicios.rotacion import ErrorRotacion

# Tipo de activo → (modelo, etiqueta legible). La interfaz clásica añade por su
# cuenta la URL de detalle, que es asunto suyo y no del caso de uso.
MODELOS_ACTIVO = {
    ACTIVO_FISICO: (ServidorFisico, "servidor físico"),
    ACTIVO_HIPERVISOR: (Hipervisor, "hipervisor"),
    ACTIVO_VM: (MaquinaVirtual, "máquina virtual"),
    ACTIVO_DISPOSITIVO: (DispositivoRed, "dispositivo de red"),
}

SERVICIOS_SUGERIDOS = ("SSH", "RDP", "iLO/IPMI", "Panel web", "Consola hipervisor",
                       "Base de datos", "Telnet", "SNMP", "Otro")


class ErrorCredencial(Exception):
    """Regla incumplida. ``codigo`` es el HTTP que le corresponde."""

    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# Un recurso que el usuario no alcanza es **inexistente** para él: distinguir
# «no existe» de «no puedes» convierte el endpoint en un oráculo que enumera el
# inventario restringido.
_NO_EXISTE = "La credencial no existe."


def resolver_activo(db: Session, tipo: str, activo_id: int):
    """Devuelve ``(instancia, etiqueta)`` del activo, o lanza."""
    if tipo not in MODELOS_ACTIVO:
        raise ErrorCredencial("Tipo de activo inválido.")
    modelo, etiqueta = MODELOS_ACTIVO[tipo]
    activo = db.get(modelo, activo_id)
    if activo is None:
        raise ErrorCredencial(f"No existe el {etiqueta} indicado.", codigo=404)
    return activo, etiqueta


def exigir_ver_activo(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> None:
    """Gestionar una credencial exige poder ver su activo.

    Impide que un operador toque credenciales de un activo que un administrador
    restringió: responde como si el activo no existiera.
    """
    if not access.puede_ver_activo(db, usuario, tipo, activo_id):
        raise ErrorCredencial("El recurso solicitado no existe.", codigo=404)


def obtener(db: Session, credencial_id: int) -> Credencial:
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise ErrorCredencial(_NO_EXISTE, codigo=404)
    return credencial


def activo_de(credencial: Credencial) -> tuple[str, int]:
    """``(tipo, id)`` del activo al que cuelga la credencial."""
    return credencial.tipo_activo, (
        credencial.servidor_fisico_id or credencial.hipervisor_id
        or credencial.maquina_virtual_id or credencial.dispositivo_red_id
    )


def obtener_gestionable(db: Session, usuario: Usuario, credencial_id: int) -> Credencial:
    """La credencial, comprobando que el usuario alcanza su activo."""
    credencial = obtener(db, credencial_id)
    tipo, activo_id = activo_de(credencial)
    exigir_ver_activo(db, usuario, tipo, activo_id)
    return credencial


def validar_puerto(puerto: int | None) -> None:
    if puerto is not None and not (1 <= puerto <= 65535):
        raise ErrorCredencial("El puerto debe ser un número entre 1 y 65535.")


# ---------------------------------------------------------------------------
# Alta, edición y baja
# ---------------------------------------------------------------------------


def crear(
    db: Session,
    *,
    usuario: Usuario,
    tipo_activo: str,
    activo_id: int,
    usuario_acceso: str,
    password: str,
    servicio: str = "SSH",
    puerto: int | None = None,
    descripcion: str = "",
    usada_por: str = "",
    request: Request | None = None,
) -> Credencial:
    """Da de alta una credencial. La contraseña la cifra el servicio de rotación."""
    instancia, etiqueta = resolver_activo(db, tipo_activo, activo_id)
    exigir_ver_activo(db, usuario, tipo_activo, activo_id)
    if not usuario_acceso.strip():
        raise ErrorCredencial("El usuario de acceso es obligatorio.")
    if not password:
        raise ErrorCredencial("La contraseña es obligatoria.")
    validar_puerto(puerto)

    credencial = rotacion_svc.nueva_credencial(
        db,
        password=password,
        usuario_acceso=usuario_acceso.strip(),
        servicio=servicio.strip() or "SSH",
        puerto=puerto,
        descripcion=descripcion.strip(),
        usada_por=usada_por.strip(),
        creado_por_id=usuario.id,
        servidor_fisico_id=activo_id if tipo_activo == ACTIVO_FISICO else None,
        hipervisor_id=activo_id if tipo_activo == ACTIVO_HIPERVISOR else None,
        maquina_virtual_id=activo_id if tipo_activo == ACTIVO_VM else None,
        dispositivo_red_id=activo_id if tipo_activo == ACTIVO_DISPOSITIVO else None,
    )
    db.flush()
    audit.registrar(db, audit.CREDENCIAL_CREADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{instancia.nombre} "
                            f"({etiqueta}, {credencial.servicio})")
    return credencial


def actualizar(
    db: Session,
    *,
    usuario: Usuario,
    credencial_id: int,
    usuario_acceso: str,
    password: str = "",
    servicio: str = "SSH",
    puerto: int | None = None,
    descripcion: str = "",
    usada_por: str = "",
    request: Request | None = None,
) -> tuple[Credencial, object | None]:
    """Actualiza la ficha y, si viene contraseña, aplica la rotación autorizada.

    Devuelve ``(credencial, rotacion_aplicada_o_None)``.

    La contraseña solo cambia bajo una rotación ya autorizada, y eso se
    comprueba **antes** de tocar ningún campo: un intento sin autorización no
    debe dejar la credencial medio editada.
    """
    credencial = obtener_gestionable(db, usuario, credencial_id)
    instancia, _etiqueta = resolver_activo(db, *activo_de(credencial))

    if not usuario_acceso.strip():
        raise ErrorCredencial("El usuario de acceso es obligatorio.")
    validar_puerto(puerto)

    autorizacion = None
    if password:
        try:
            autorizacion = rotacion_svc.exigir_autorizacion(db, credencial)
        except ErrorRotacion as exc:
            audit.registrar(db, audit.ROTACION_ESCRITURA_DENEGADA, request=request, usuario=usuario,
                            objeto_tipo="credencial", objeto_id=credencial.id,
                            detalle="Intento de cambiar la contraseña sin rotación autorizada",
                            exito=False)
            db.commit()  # la evidencia del intento sobrevive al error que sigue
            raise ErrorCredencial(exc.mensaje, codigo=exc.codigo) from exc

    credencial.usuario_acceso = usuario_acceso.strip()
    credencial.servicio = servicio.strip() or "SSH"
    credencial.puerto = puerto
    credencial.descripcion = descripcion.strip()
    credencial.usada_por = usada_por.strip()

    if autorizacion is not None:
        try:
            rotacion_svc.registrar_rotacion_manual(
                db, rotacion=autorizacion, password=password, usuario=usuario, request=request,
            )
        except ErrorRotacion as exc:
            raise ErrorCredencial(exc.mensaje, codigo=exc.codigo) from exc
        avisos.aviso_rotacion_aplicada(db, autorizacion)

    audit.registrar(db, audit.CREDENCIAL_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{instancia.nombre}"
                            + (" — contraseña rotada" if autorizacion is not None else ""))
    # Se avisa a los DEMÁS usuarios con acceso de que la credencial cambió. El
    # correo comunica el HECHO —activo, servicio, quién y cuándo—, nunca la
    # contraseña: quien la necesite la revela en la aplicación, donde el acceso
    # se comprueba, se limita y queda en la bitácora.
    avisos.aviso_credencial_compartida_actualizada(
        db, credencial, usuario, password_cambiada=autorizacion is not None
    )
    return credencial, autorizacion


def eliminar(
    db: Session,
    *,
    usuario: Usuario,
    credencial_id: int,
    request: Request | None = None,
) -> None:
    credencial = obtener_gestionable(db, usuario, credencial_id)
    detalle = f"{credencial.usuario_acceso}@{credencial.nombre_activo} ({credencial.servicio})"
    db.delete(credencial)
    audit.registrar(db, audit.CREDENCIAL_ELIMINADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial_id, detalle=detalle)


def detalle_para_editar(db: Session, usuario: Usuario, credencial_id: int) -> dict:
    """Datos de la ficha, **sin la contraseña**, con su historial."""
    credencial = obtener_gestionable(db, usuario, credencial_id)
    tipo, activo_id = activo_de(credencial)
    return {
        "id": credencial.id,
        "usuario_acceso": credencial.usuario_acceso,
        "servicio": credencial.servicio,
        "puerto": credencial.puerto,
        "descripcion": credencial.descripcion,
        "usada_por": credencial.usada_por,
        "via_rotacion": credencial.via_rotacion,
        "tipo_activo": tipo,
        "activo_id": activo_id,
        "activo_nombre": credencial.nombre_activo,
        "dias_sin_rotar": credencial.dias_sin_rotar,
        "historial": [
            {
                "id": h.id,
                "rotada_en": h.rotada_en.isoformat(),
                "rotada_por": h.rotada_por.username if h.rotada_por else None,
            }
            for h in credencial.historial
        ],
    }


# ---------------------------------------------------------------------------
# Entrega de secretos
# ---------------------------------------------------------------------------
#
# Esta es la parte que estaba escrita dos veces. El orden de los controles es
# deliberado y cada paso deja rastro:
#
#   1. ¿Existe?                → 404
#   2. ¿Puede VER el activo?   → 404 (no «403»: un activo restringido debe ser
#                                 indistinguible de uno inexistente)
#   3. ¿Puede REVELAR?         → 403 (ve el activo, pero su concesión no llega)
#   4. ¿Dentro del límite?     → 429 + alerta al equipo de seguridad
#
# El límite por usuario, compartido entre revelar y copiar, frena la extracción
# masiva del inventario aun con una sesión legítima comprometida
# (OWASP API4/API6).


def _exigir_limite_de_revelado(
    db: Session,
    usuario: Usuario,
    *,
    objeto_tipo: str,
    objeto_id: int,
    request: Request | None,
    alertar: bool,
) -> None:
    settings = get_settings()
    if ratelimit.permitir_intento(
        f"revelar:{usuario.id}",
        limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes,
        db=db,
    ):
        return

    audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                    objeto_tipo=objeto_tipo, objeto_id=objeto_id,
                    detalle=f"Límite de {settings.reveal_rate_limit} accesos "
                            f"en {settings.reveal_rate_window_minutes} min superado.",
                    exito=False)
    db.commit()  # conservar la evidencia pese al error que sigue
    if alertar:
        enviar_alerta(
            "Posible exfiltración de credenciales",
            f"El usuario «{usuario.username}» superó el límite de accesos a contraseñas "
            f"({settings.reveal_rate_limit} en {settings.reveal_rate_window_minutes} min).",
        )
    raise ErrorCredencial(
        "Límite de accesos a contraseñas alcanzado; espere unos minutos.", codigo=429,
    )


def entregar_password(
    db: Session,
    *,
    usuario: Usuario,
    credencial_id: int,
    accion: str,
    request: Request | None = None,
    sesion_id: int | None = None,
) -> dict:
    """Entrega la contraseña en claro. ``accion`` es el evento de auditoría.

    Devuelve ``{"usuario": ..., "password": ...}``. Quien lo llame debe servirlo
    con ``Cache-Control: no-store``.
    """
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise ErrorCredencial(_NO_EXISTE, codigo=404)

    if not access.puede_ver_credencial(db, usuario, credencial):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo="credencial", objeto_id=credencial_id,
                        detalle="Acceso a credencial sin concesión vigente.", exito=False)
        db.commit()
        raise ErrorCredencial(_NO_EXISTE, codigo=404)
    if not access.puede_revelar_credencial(db, usuario, credencial):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo="credencial", objeto_id=credencial_id,
                        detalle="Concesión sin nivel para revelar/copiar credenciales.", exito=False)
        db.commit()
        raise ErrorCredencial("No tiene permiso para usar esta credencial.", codigo=403)

    _exigir_limite_de_revelado(db, usuario, objeto_tipo="credencial",
                               objeto_id=credencial_id, request=request, alertar=True)

    via = " (vía concesión)" if usuario.rol == ROL_ANALISTA else ""
    audit.registrar(db, accion, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} "
                            f"({credencial.servicio}){via}")
    _avisar_revelado(db, usuario, credencial, sesion_id)
    return {"usuario": credencial.usuario_acceso,
            "password": descifrar(credencial.password_cifrada)}


def revelar_historial(
    db: Session,
    *,
    usuario: Usuario,
    credencial_id: int,
    historial_id: int,
    request: Request | None = None,
) -> dict:
    """Entrega una contraseña ANTERIOR, bajo el mismo límite que las vigentes."""
    entrada = db.get(HistorialCredencial, historial_id)
    sin_entrada = ErrorCredencial("La entrada de historial no existe.", codigo=404)
    if entrada is None or entrada.credencial_id != credencial_id:
        raise sin_entrada
    credencial = db.get(Credencial, credencial_id)
    if credencial is None or not access.puede_revelar_credencial(db, usuario, credencial):
        raise sin_entrada

    _exigir_limite_de_revelado(db, usuario, objeto_tipo="historial_credencial",
                               objeto_id=historial_id, request=request, alertar=False)

    audit.registrar(db, audit.HISTORIAL_REVELADO, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial_id,
                    detalle=f"Contraseña anterior del {entrada.rotada_en:%d/%m/%Y %H:%M}")
    return {"password": descifrar(entrada.password_cifrada)}


def _avisar_revelado(
    db: Session, usuario: Usuario, credencial: Credencial, sesion_id: int | None
) -> None:
    """Avisa al titular de que reveló una credencial en su sesión (mejor esfuerzo).

    Deduplicado por sesión y categoría: el primer revelado de la sesión genera
    un correo y los siguientes no. Así el aviso conserva su valor de detección
    sin convertir el trabajo normal en decenas de mensajes, que acabarían
    filtrados.
    """
    if sesion_id is None:
        return
    avisos.aviso_actividad_sensible(
        db, usuario, sesion_id, "revelado",
        f"reveló o copió una contraseña del inventario "
        f"({credencial.usuario_acceso}@{credencial.nombre_activo})",
    )
