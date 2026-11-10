"""Gestión de sesiones en servidor.

- Token aleatorio de 256 bits en cookie HttpOnly/SameSite=Strict; en BD solo
  se guarda su hash SHA-256.
- Doble expiración: absoluta (vida máxima) e inactividad (CIS 4.3).
- El token se rota al completar el MFA para impedir fijación de sesión.
- Revocación inmediata en servidor (cierre de sesión, desactivación de cuenta).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SesionWeb, Usuario, ahora_utc

COOKIE_SESION = "passwd_session"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def crear_sesion(
    db: Session,
    usuario: Usuario,
    etapa: str,
    direccion_ip: str,
    agente_usuario: str,
) -> tuple[SesionWeb, str]:
    """Crea una sesión y devuelve (registro, token_para_cookie)."""
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    sesion = SesionWeb(
        token_hash=_hash_token(token),
        usuario_id=usuario.id,
        etapa=etapa,
        csrf_token=secrets.token_urlsafe(32),
        expira_en=ahora_utc() + timedelta(hours=settings.session_max_hours),
        direccion_ip=direccion_ip[:45],
        agente_usuario=agente_usuario[:255],
    )
    db.add(sesion)
    db.flush()
    return sesion, token


def _amortiguacion_efectiva(settings) -> int:
    """Segundos de amortiguación de la marca de actividad, nunca más de la mitad
    de la ventana de inactividad (si no, una sesión en uso podría caducar)."""
    return min(settings.activity_throttle_seconds, settings.session_idle_minutes * 30)


def buscar_sesion_valida(db: Session, token: str, tocar: bool = True) -> SesionWeb | None:
    """Devuelve la sesión si existe y no está revocada ni expirada.

    Con ``tocar=False`` la consulta NO cuenta como actividad: la usa el sondeo de
    estado del frontend, que no debe prolongar por sí solo una sesión inactiva.
    """
    if not token:
        return None
    sesion = db.scalar(select(SesionWeb).where(SesionWeb.token_hash == _hash_token(token)))
    if sesion is None or sesion.revocada_en is not None:
        return None
    ahora = ahora_utc()
    settings = get_settings()
    inactividad_maxima = timedelta(minutes=settings.session_idle_minutes)
    inactiva = ahora - sesion.ultima_actividad
    if sesion.expira_en <= ahora or inactiva > inactividad_maxima:
        sesion.revocada_en = ahora
        return None
    # Amortiguar la escritura: solo actualizar la marca si pasó el umbral, para
    # no escribir en la BD en cada petición (una por acción sería costoso).
    if tocar and inactiva.total_seconds() >= _amortiguacion_efectiva(settings):
        sesion.ultima_actividad = ahora
    return sesion


def plazos(sesion: SesionWeb) -> dict[str, int]:
    """Segundos que le quedan a la sesión, para que el cliente avise antes de que
    venza: por inactividad, por vida máxima, la ventana de inactividad completa y
    el margen de imprecisión de la marca de actividad (amortiguación)."""
    settings = get_settings()
    ahora = ahora_utc()
    ventana = settings.session_idle_minutes * 60
    inactiva = int((ahora - sesion.ultima_actividad).total_seconds())
    return {
        "idle_expires_in": max(0, ventana - inactiva),
        "absolute_expires_in": max(0, int((sesion.expira_en - ahora).total_seconds())),
        "idle_timeout": ventana,
        "margin": _amortiguacion_efectiva(settings),
    }


def extender(sesion: SesionWeb) -> None:
    """Renueva la ventana de inactividad a petición expresa del usuario.

    No altera ``expira_en``: la vida máxima absoluta nunca se prolonga."""
    sesion.ultima_actividad = ahora_utc()


def rotar_token(db: Session, sesion: SesionWeb) -> str:
    """Reemplaza el token (anti fijación de sesión) y devuelve el nuevo valor."""
    token = secrets.token_urlsafe(32)
    sesion.token_hash = _hash_token(token)
    sesion.csrf_token = secrets.token_urlsafe(32)
    db.flush()
    return token


def revocar_sesion(sesion: SesionWeb) -> None:
    sesion.revocada_en = ahora_utc()


def revocar_sesiones_de_usuario(db: Session, usuario_id: int) -> int:
    """Revoca todas las sesiones vivas de un usuario (CIS 6.2 — revocación)."""
    sesiones = db.scalars(
        select(SesionWeb).where(SesionWeb.usuario_id == usuario_id, SesionWeb.revocada_en.is_(None))
    ).all()
    for sesion in sesiones:
        sesion.revocada_en = ahora_utc()
    return len(sesiones)


def purgar_sesiones_expiradas(db: Session) -> int:
    """Elimina registros de sesiones vencidas hace más de 7 días."""
    limite = ahora_utc() - timedelta(days=7)
    antiguas = db.scalars(select(SesionWeb).where(SesionWeb.expira_en < limite)).all()
    for sesion in antiguas:
        db.delete(sesion)
    return len(antiguas)


def configurar_cookie(respuesta, token: str) -> None:
    settings = get_settings()
    respuesta.set_cookie(
        key=COOKIE_SESION,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_max_hours * 3600,
        path="/",
    )


def borrar_cookie(respuesta) -> None:
    respuesta.delete_cookie(COOKIE_SESION, path="/")


def cabecera_borrar_cookie() -> dict[str, str]:
    """Cabecera ``Set-Cookie`` que elimina la cookie de sesión, para adjuntarla a
    un error (p. ej. el 401 de una sesión vencida) y que el navegador no conserve
    una cookie que ya no abre nada."""
    seguro = "; Secure" if get_settings().cookie_secure else ""
    return {"Set-Cookie": f'{COOKIE_SESION}=""; Max-Age=0; Path=/; HttpOnly; SameSite=strict{seguro}'}
