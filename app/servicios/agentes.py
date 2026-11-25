"""Agentes de rotación: alta, enrolamiento, identidad y cobertura (v1.4.0).

Un agente es un binario instalado en un activo Linux que, más adelante, aplicará
las rotaciones **ya autorizadas** de ese activo. Este módulo gobierna quién es
cada agente; qué trabajos recibe y cómo se cierran vive en
``app/servicios/rotacion.py``, que sigue siendo el único punto que escribe una
contraseña del inventario.

Ciclo de vida (docs/plan-rotacion-agentes.md §4.5):

    alta (panel) ──► PENDIENTE ──enrolar(token de un uso)──► ACTIVO ──► REVOCADO
                        ▲                                       │
                        └────────── reemitir_enrolamiento ──────┘

**Identidad de vida corta** (§2.1). El token del agente caduca en
``agentes_token_vida_horas`` y se renueva en cada latido al entrar en su último
cuarto de vida; el anterior sigue valiendo un solapamiento corto, para no dejar
fuera a un agente que no llegó a recibir la respuesta. Un token robado del disco
de un servidor caduca en horas, y un binario olvidado en una máquina dada de baja
no conserva acceso: pasado el plazo, hay que volver a enrolarlo desde el panel.

Solo se guarda el **hash** de cada token, como con las sesiones y los tokens de
API: un volcado de la base de datos no permite hacerse pasar por un agente.

**Cobertura derivada.** Lo que se guarda del agente es lo que decide una persona
o el enrolamiento (pendiente, activo, revocado). «Conectado», «sin contacto» y
«caducado» se calculan al consultarlos a partir de las fechas: así la insignia no
puede mentir porque un proceso de fondo dejara de correr.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, notifications
from app.config import get_settings
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    AGENTE_ACTIVO,
    AGENTE_PENDIENTE,
    AGENTE_REVOCADO,
    VIA_ROTACION_AGENTE,
    VIA_ROTACION_MANUAL,
    Agente,
    Configuracion,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
    vinculo_activo,
)
from app.servicios import cifrado_agente

# Activos que admiten agente. Los dispositivos de red no: los cubrirán los
# conectores de la 2.3.0 (§6), porque no se les puede instalar un binario.
MODELOS_ACTIVO = {
    ACTIVO_FISICO: (ServidorFisico, "servidor físico"),
    ACTIVO_HIPERVISOR: (Hipervisor, "hipervisor"),
    ACTIVO_VM: (MaquinaVirtual, "máquina virtual"),
}

# El token de enrolamiento se usa una vez, en la instalación. Corto a propósito:
# quien lo copia de la pantalla lo pega en el instalador a continuación.
VIDA_ENROLAMIENTO = timedelta(hours=1)
# Tras una renovación, el token anterior sigue valiendo este tiempo.
SOLAPAMIENTO = timedelta(minutes=30)

# Insignias de cobertura (§5). La interfaz decide el color; aquí solo el hecho.
COBERTURA_SIN_AGENTE = "sin_agente"     # ⚪
COBERTURA_PENDIENTE = "pendiente"       # 🟠 dado de alta, aún sin enrolar
COBERTURA_CONECTADO = "conectado"       # 🟢
COBERTURA_SIN_CONTACTO = "sin_contacto"  # 🟡 enrolado, pero callado más de la cuenta
COBERTURA_CADUCADO = "caducado"         # 🔴 identidad vencida: hay que re-enrolar

_LARGO_NOMBRE = 120
_LARGO_HOST = 255
_LARGO_VERSION = 40


class ErrorAgente(Exception):
    """Regla de los agentes incumplida. ``codigo`` es el HTTP que le corresponde."""

    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def habilitados() -> bool:
    return bool(get_settings().agentes_enabled)


def _exigir_habilitados() -> None:
    if not habilitados():
        raise ErrorAgente(
            "Los agentes de rotación están desactivados en la configuración "
            "(agentes_enabled).", codigo=409,
        )


def vida_token() -> timedelta:
    return timedelta(hours=max(get_settings().agentes_token_vida_horas, 1))


def sujeto(agente: Agente) -> str:
    """Nombre con el que un agente figura en la bitácora."""
    return f"agente:{agente.nombre}"[:64]


def activo_de_credencial(credencial: Credencial) -> tuple[str, int]:
    tipo = credencial.tipo_activo
    activo_id = (credencial.servidor_fisico_id or credencial.hipervisor_id
                 or credencial.maquina_virtual_id or credencial.dispositivo_red_id)
    return tipo, int(activo_id)  # type: ignore[arg-type]


def agente_vigente_de(db: Session, tipo: str, activo_id: int) -> Agente | None:
    """El agente no revocado de un activo, si lo hay. Solo puede haber uno."""
    return db.scalar(select(Agente).where(Agente.vinculo_vigente == vinculo_activo(tipo, activo_id)))


def nombre_activo(agente: Agente) -> str:
    activo = agente.servidor_fisico or agente.hipervisor or agente.maquina_virtual
    return activo.nombre if activo is not None else "—"


# ---------------------------------------------------------------------------
# Alta y enrolamiento
# ---------------------------------------------------------------------------


def alta(
    db: Session,
    *,
    tipo_activo: str,
    activo_id: int,
    nombre: str,
    usuario: Usuario,
    request: Request | None = None,
) -> tuple[Agente, str]:
    """Da de alta el agente de un activo. Devuelve el token de enrolamiento **una vez**."""
    _exigir_habilitados()
    if tipo_activo == ACTIVO_DISPOSITIVO:
        raise ErrorAgente(
            "Los dispositivos de red no admiten agente: no se les puede instalar un "
            "binario. Su rotación será por conector (versión 2.3.0).",
        )
    if tipo_activo not in MODELOS_ACTIVO:
        raise ErrorAgente(f"Tipo de activo desconocido: {tipo_activo}.")
    modelo, etiqueta = MODELOS_ACTIVO[tipo_activo]
    activo = db.get(modelo, activo_id)
    if activo is None:
        raise ErrorAgente(f"No existe ese {etiqueta}.", codigo=404)

    nombre_limpio = (nombre or "").strip()[:_LARGO_NOMBRE]
    if not nombre_limpio:
        raise ErrorAgente("El agente necesita un nombre.")
    if db.scalar(select(Agente.id).where(Agente.nombre == nombre_limpio)) is not None:
        raise ErrorAgente("Ya existe un agente con ese nombre.", codigo=409)
    if agente_vigente_de(db, tipo_activo, activo_id) is not None:
        raise ErrorAgente(
            f"Este {etiqueta} ya tiene un agente. Revóquelo antes de dar de alta otro.",
            codigo=409,
        )

    token = _nuevo_token()
    agente = Agente(
        nombre=nombre_limpio,
        servidor_fisico_id=activo_id if tipo_activo == ACTIVO_FISICO else None,
        hipervisor_id=activo_id if tipo_activo == ACTIVO_HIPERVISOR else None,
        maquina_virtual_id=activo_id if tipo_activo == ACTIVO_VM else None,
        vinculo_vigente=vinculo_activo(tipo_activo, activo_id),
        estado=AGENTE_PENDIENTE,
        enrolamiento_hash=_hash(token),
        enrolamiento_expira_en=ahora_utc() + VIDA_ENROLAMIENTO,
        creado_por_id=usuario.id,
    )
    db.add(agente)
    db.flush()
    audit.registrar(
        db, audit.AGENTE_ALTA, request=request, usuario=usuario,
        objeto_tipo="agente", objeto_id=agente.id,
        detalle=f"{agente.nombre} en {etiqueta} «{activo.nombre}»",
    )
    return agente, token


def reemitir_enrolamiento(
    db: Session, *, agente: Agente, usuario: Usuario, request: Request | None = None,
) -> str:
    """Emite un token de enrolamiento nuevo y **anula la identidad vigente**.

    Es el camino para un agente cuya identidad caducó (estuvo apagado más tiempo
    que su vida) o cuyo servidor se reinstaló: vuelve a pendiente hasta que se
    enrole de nuevo con un par de claves nuevo.
    """
    _exigir_habilitados()
    if agente.revocado:
        raise ErrorAgente("Un agente revocado no se puede volver a enrolar: dé de alta otro.",
                          codigo=409)
    token = _nuevo_token()
    agente.estado = AGENTE_PENDIENTE
    agente.enrolamiento_hash = _hash(token)
    agente.enrolamiento_expira_en = ahora_utc() + VIDA_ENROLAMIENTO
    agente.token_hash = None
    agente.token_expira_en = None
    agente.token_anterior_hash = None
    agente.token_anterior_expira_en = None
    audit.registrar(
        db, audit.AGENTE_ENROLAMIENTO_EMITIDO, request=request, usuario=usuario,
        objeto_tipo="agente", objeto_id=agente.id,
        detalle=f"{agente.nombre}: nuevo token de enrolamiento; la identidad anterior queda anulada",
    )
    return token


def enrolar(
    db: Session,
    *,
    token_enrolamiento: str,
    clave_publica: str,
    nombre_host: str,
    version: str,
    ip: str,
    request: Request | None = None,
) -> tuple[Agente, str]:
    """Canjea el token de un solo uso por la identidad del agente.

    El token de enrolamiento se **anula** al canjearlo, de modo que un segundo
    uso no encuentra nada que validar. Devuelve el token de identidad una vez;
    en la base de datos solo queda su hash.
    """
    _exigir_habilitados()
    agente = db.scalar(select(Agente).where(Agente.enrolamiento_hash == _hash(token_enrolamiento or "")))
    if agente is None or agente.estado != AGENTE_PENDIENTE:
        audit.registrar(db, audit.AGENTE_ENROLAMIENTO_RECHAZADO, request=request,
                        username="agente:desconocido", objeto_tipo="agente",
                        detalle="Token de enrolamiento inexistente o ya usado", exito=False)
        raise ErrorAgente("Token de enrolamiento no válido o ya usado.", codigo=401)
    if agente.enrolamiento_expira_en is None or agente.enrolamiento_expira_en <= ahora_utc():
        audit.registrar(db, audit.AGENTE_ENROLAMIENTO_RECHAZADO, request=request,
                        username=sujeto(agente), objeto_tipo="agente", objeto_id=agente.id,
                        detalle="Token de enrolamiento caducado", exito=False)
        raise ErrorAgente("El token de enrolamiento caducó: emita otro desde el panel.", codigo=401)
    try:
        clave = cifrado_agente.validar_clave_publica(clave_publica)
    except cifrado_agente.ErrorCifradoAgente as exc:
        raise ErrorAgente(str(exc)) from exc

    ahora = ahora_utc()
    token = _nuevo_token()
    agente.estado = AGENTE_ACTIVO
    agente.enrolamiento_hash = None
    agente.enrolamiento_expira_en = None
    agente.enrolado_en = ahora
    agente.clave_publica = clave
    agente.clave_huella = cifrado_agente.huella(clave)
    agente.nombre_host = (nombre_host or "").strip()[:_LARGO_HOST]
    agente.version_agente = (version or "").strip()[:_LARGO_VERSION]
    agente.token_hash = _hash(token)
    agente.token_expira_en = ahora + vida_token()
    agente.token_anterior_hash = None
    agente.token_anterior_expira_en = None
    agente.token_renovado_en = ahora
    agente.ip_ultima_renovacion = (ip or "")[:45]
    agente.ultimo_contacto_en = ahora
    agente.ip_ultimo_contacto = (ip or "")[:45]
    audit.registrar(
        db, audit.AGENTE_ENROLADO, request=request, username=sujeto(agente),
        objeto_tipo="agente", objeto_id=agente.id,
        detalle=f"Host «{agente.nombre_host}», versión {agente.version_agente or '?'}, "
                f"clave {agente.clave_huella[:16]}…",
    )
    return agente, token


# ---------------------------------------------------------------------------
# Identidad: autenticación y renovación
# ---------------------------------------------------------------------------


def autenticar(db: Session, token: str) -> tuple[Agente, bool] | None:
    """Agente dueño del token, e indica si entró con el token **anterior**.

    Vale el token vigente sin caducar, o el anterior dentro de su solapamiento.
    Un agente pendiente o revocado no tiene identidad que presentar.
    """
    if not token or not habilitados():
        return None
    h = _hash(token)
    ahora = ahora_utc()
    agente = db.scalar(select(Agente).where(Agente.token_hash == h))
    if agente is not None:
        vigente = agente.token_expira_en is not None and agente.token_expira_en > ahora
        return (agente, False) if agente.estado == AGENTE_ACTIVO and vigente else None
    agente = db.scalar(select(Agente).where(Agente.token_anterior_hash == h))
    if agente is not None:
        vigente = agente.token_anterior_expira_en is not None and agente.token_anterior_expira_en > ahora
        return (agente, True) if agente.estado == AGENTE_ACTIVO and vigente else None
    return None


def _debe_renovar(agente: Agente, ahora: datetime, con_anterior: bool) -> bool:
    # Si entró con el token anterior es que no llegó a recibir el nuevo: se le
    # emite otro (solo se guarda el hash, el anterior no se puede reenviar).
    if con_anterior or agente.token_expira_en is None:
        return True
    return agente.token_expira_en - ahora <= vida_token() / 4


def saludo(
    db: Session,
    *,
    agente: Agente,
    ip: str,
    version: str,
    con_token_anterior: bool = False,
    request: Request | None = None,
) -> dict:
    """Latido del agente: registra el contacto y renueva la identidad si toca."""
    ahora = ahora_utc()
    ip = (ip or "")[:45]
    agente.ultimo_contacto_en = ahora
    agente.ip_ultimo_contacto = ip
    if version:
        agente.version_agente = version.strip()[:_LARGO_VERSION]

    token_nuevo: str | None = None
    if _debe_renovar(agente, ahora, con_token_anterior):
        _vigilar_ip_de_renovacion(db, agente, ip, ahora, request)
        token_nuevo = _nuevo_token()
        if not con_token_anterior:
            # El vigente pasa a anterior durante el solapamiento.
            agente.token_anterior_hash = agente.token_hash
            agente.token_anterior_expira_en = ahora + SOLAPAMIENTO
        agente.token_hash = _hash(token_nuevo)
        agente.token_expira_en = ahora + vida_token()
        agente.token_renovado_en = ahora
        agente.ip_ultima_renovacion = ip
        audit.registrar(
            db, audit.AGENTE_TOKEN_RENOVADO, request=request, username=sujeto(agente),
            objeto_tipo="agente", objeto_id=agente.id,
            detalle="Identidad renovada" + (" tras usar el token anterior" if con_token_anterior else ""),
        )

    admitida, en_gracia = version_admitida(db, agente)
    return {
        "token_nuevo": token_nuevo,
        "token_expira_en": agente.token_expira_en,
        "intervalo_min": max(get_settings().agentes_telemetria_intervalo_min, 1),
        "version_minima": get_settings().agentes_version_minima or "",
        "version_admitida": admitida,
        "version_en_gracia": en_gracia,
    }


def _vigilar_ip_de_renovacion(db: Session, agente: Agente, ip: str, ahora: datetime,
                              request: Request | None) -> None:
    """Dos renovaciones desde IPs distintas dentro de una misma vida: anomalía (§3.8).

    El agente legítimo renueva desde su servidor; si la renovación anterior, aún
    reciente, vino de otra dirección, alguien más puede tener el token. Detrás de
    un NAT con varias salidas da falsos positivos: por eso se puede apagar el
    aviso, pero el asiento en la bitácora se deja siempre.
    """
    anterior = agente.ip_ultima_renovacion
    if not anterior or not ip or anterior == ip or agente.token_renovado_en is None:
        return
    if ahora - agente.token_renovado_en > vida_token():
        return
    audit.registrar(
        db, audit.AGENTE_ANOMALIA_IP, request=request, username=sujeto(agente),
        objeto_tipo="agente", objeto_id=agente.id, exito=False,
        detalle=f"Renovación desde {ip}; la anterior, hace "
                f"{int((ahora - agente.token_renovado_en).total_seconds() // 60)} min, vino de {anterior}",
    )
    if get_settings().agentes_alertar_ip_distinta:
        notifications.enviar_alerta(
            f"[passwd] Agente {agente.nombre}: identidad renovada desde otra IP",
            f"El agente «{agente.nombre}» ({nombre_activo(agente)}) renovó su identidad desde "
            f"{ip}, y la renovación anterior, reciente, vino de {anterior}.\n\n"
            "Puede ser un cambio de red legítimo o un token copiado de ese servidor. Si no lo "
            "reconoce, revoque el agente desde el panel y vuelva a enrolarlo.",
        )


# ---------------------------------------------------------------------------
# Revocación, versión y cobertura
# ---------------------------------------------------------------------------


def revocar(
    db: Session, *, agente: Agente, usuario: Usuario, request: Request | None = None,
) -> Agente:
    """Retira la identidad del agente y devuelve su activo al flujo manual.

    El agente se conserva como historia (el libro mayor lo nombra), pero deja de
    ocupar el activo: ``vinculo_vigente`` a NULL permite dar de alta otro. Las
    credenciales del activo que rotaban por agente vuelven a ``manual``: una
    credencial que dice rotar por un agente que ya no existe es un estado
    fantasma.
    """
    if agente.revocado:
        raise ErrorAgente("El agente ya está revocado.", codigo=409)
    tipo, activo_id = agente.tipo_activo, agente.activo_id
    agente.estado = AGENTE_REVOCADO
    agente.vinculo_vigente = None
    agente.enrolamiento_hash = None
    agente.enrolamiento_expira_en = None
    agente.token_hash = None
    agente.token_expira_en = None
    agente.token_anterior_hash = None
    agente.token_anterior_expira_en = None
    agente.revocado_en = ahora_utc()
    agente.revocado_por_id = usuario.id

    devueltas = 0
    for credencial in _credenciales_del_activo(db, tipo, activo_id):
        if credencial.via_rotacion == VIA_ROTACION_AGENTE:
            credencial.via_rotacion = VIA_ROTACION_MANUAL
            devueltas += 1
    audit.registrar(
        db, audit.AGENTE_REVOCADO, request=request, usuario=usuario,
        objeto_tipo="agente", objeto_id=agente.id,
        detalle=f"{agente.nombre} ({nombre_activo(agente)}); {devueltas} credencial(es) "
                "devueltas al flujo manual",
    )
    return agente


def _credenciales_del_activo(db: Session, tipo: str, activo_id: int) -> list[Credencial]:
    columna = {
        ACTIVO_FISICO: Credencial.servidor_fisico_id,
        ACTIVO_HIPERVISOR: Credencial.hipervisor_id,
        ACTIVO_VM: Credencial.maquina_virtual_id,
    }[tipo]
    return list(db.scalars(select(Credencial).where(columna == activo_id)).all())


def _version_tupla(texto: str) -> tuple[int, int, int] | None:
    partes = (texto or "").strip().lstrip("v").split(".")
    if len(partes) != 3:
        return None
    try:
        return int(partes[0]), int(partes[1]), int(partes[2].split("-")[0])
    except ValueError:
        return None


def version_admitida(db: Session, agente: Agente) -> tuple[bool, bool]:
    """¿Puede este agente recibir trabajos por su versión? Devuelve (admitida, en_gracia).

    La gracia cuenta desde que se fijó el mínimo **en el panel**
    (``Configuracion.actualizado_en``). Fijado por variable de entorno no hay
    fecha de la que contar, y rige sin gracia: está documentado así.
    """
    settings = get_settings()
    minima = _version_tupla(settings.agentes_version_minima)
    if minima is None:
        return True, False
    propia = _version_tupla(agente.version_agente)
    if propia is not None and propia >= minima:
        return True, False
    fijada = db.scalar(select(Configuracion.actualizado_en)
                       .where(Configuracion.clave == "agentes_version_minima"))
    if fijada is not None:
        gracia = timedelta(days=max(settings.agentes_gracia_version_dias, 0))
        if ahora_utc() < fijada + gracia:
            return True, True
    return False, False


def cobertura(agente: Agente | None, ahora: datetime | None = None) -> str:
    """Estado que muestra la insignia del activo. Siempre derivado de las fechas."""
    if agente is None or agente.revocado:
        return COBERTURA_SIN_AGENTE
    if agente.estado == AGENTE_PENDIENTE:
        return COBERTURA_PENDIENTE
    ahora = ahora or ahora_utc()
    if agente.token_expira_en is None or agente.token_expira_en <= ahora:
        return COBERTURA_CADUCADO
    umbral = timedelta(hours=max(get_settings().agentes_umbral_sin_contacto_horas, 1))
    if agente.ultimo_contacto_en is None or ahora - agente.ultimo_contacto_en > umbral:
        return COBERTURA_SIN_CONTACTO
    return COBERTURA_CONECTADO


# ---------------------------------------------------------------------------
# Vía de rotación de una credencial
# ---------------------------------------------------------------------------


def usar_agente(
    db: Session, *, credencial: Credencial, usuario: Usuario, request: Request | None = None,
) -> Credencial:
    """La credencial pasa a rotarse por el agente de **su** activo."""
    _exigir_habilitados()
    tipo, activo_id = activo_de_credencial(credencial)
    if tipo == ACTIVO_DISPOSITIVO:
        raise ErrorAgente("Las credenciales de dispositivos de red no pueden rotar por agente.")
    agente = agente_vigente_de(db, tipo, activo_id)
    if agente is None or agente.estado != AGENTE_ACTIVO:
        raise ErrorAgente(
            "El activo de esta credencial no tiene un agente enrolado. Dé de alta el agente "
            "e instálelo antes de cambiar la vía de rotación.", codigo=409,
        )
    return _cambiar_via(db, credencial, VIA_ROTACION_AGENTE, usuario, request,
                        f"por el agente {agente.nombre}")


def usar_manual(
    db: Session, *, credencial: Credencial, usuario: Usuario, request: Request | None = None,
) -> Credencial:
    """La credencial vuelve a rotarse a mano."""
    return _cambiar_via(db, credencial, VIA_ROTACION_MANUAL, usuario, request, "a mano")


def _cambiar_via(db: Session, credencial: Credencial, via: str, usuario: Usuario,
                 request: Request | None, explicacion: str) -> Credencial:
    from app.models import ROT_DESPACHADA
    from app.servicios.rotacion import solicitud_abierta

    abierta = solicitud_abierta(db, credencial.id)
    if abierta is not None and abierta.estado == ROT_DESPACHADA:
        raise ErrorAgente(
            "Hay una rotación despachada a un agente para esta credencial. Espere a que "
            "se cierre antes de cambiar la vía.", codigo=409,
        )
    if credencial.via_rotacion == via:
        return credencial
    credencial.via_rotacion = via
    audit.registrar(
        db, audit.CREDENCIAL_VIA_CAMBIADA, request=request, usuario=usuario,
        objeto_tipo="credencial", objeto_id=credencial.id,
        detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} se rotará {explicacion}",
    )
    return credencial
