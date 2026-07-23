"""Desafíos de auto-recuperación de contraseña (server-side, efímeros).

El usuario que olvidó su contraseña prueba su identidad (usuario + email) y
después la posesión de su segundo factor (código TOTP en vivo o un código de
recuperación de un solo uso) para autorizar el cambio. Este módulo encapsula el
ciclo de vida del desafío; la validación del segundo factor y de la política de
contraseñas vive en ``app.security.mfa`` / ``app.security.recovery`` /
``app.security.passwords``, y los endpoints (JSON y Jinja) orquestan el flujo.

Solo se persiste el hash SHA-256 del token del desafío; la cookie efímera lleva
el valor en claro. El desafío caduca a los ``TTL_MINUTOS`` minutos y se invalida
al superar ``MAX_INTENTOS`` verificaciones fallidas.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import RecuperacionPassword, ahora_utc

TTL_MINUTOS = 10
MAX_INTENTOS = 5


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def crear_desafio(db: Session, usuario_id: int | None) -> tuple[str, str]:
    """Crea un desafío y devuelve ``(token, csrf_token)``.

    Con ``usuario_id`` real invalida antes los desafíos abiertos de ese usuario;
    con ``usuario_id=None`` crea un desafío **señuelo** (identidad no coincidente)
    para que el paso de verificación responda igual exista o no la cuenta. El
    trabajo de BD es idéntico en ambos casos, cerrando también el canal de tiempo.
    El token va en la cookie efímera; el csrf, al cliente para el doble envío.
    """
    db.execute(
        update(RecuperacionPassword)
        .where(
            RecuperacionPassword.usuario_id == usuario_id,
            RecuperacionPassword.consumido_en.is_(None),
        )
        .values(consumido_en=ahora_utc())
    )
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.add(
        RecuperacionPassword(
            usuario_id=usuario_id,
            token_hash=_hash(token),
            csrf_token=csrf,
            expira_en=ahora_utc() + timedelta(minutes=TTL_MINUTOS),
        )
    )
    db.flush()
    return token, csrf


def desafio_vigente(db: Session, token: str | None) -> RecuperacionPassword | None:
    """Desafío no consumido ni caducado asociado al token, o None."""
    if not token:
        return None
    desafio = db.scalar(
        select(RecuperacionPassword).where(RecuperacionPassword.token_hash == _hash(token))
    )
    if desafio is None or not desafio.vigente:
        return None
    return desafio


def registrar_fallo(db: Session, desafio: RecuperacionPassword) -> bool:
    """Suma un intento fallido; consume el desafío si alcanza el tope.

    Devuelve True si el desafío quedó agotado (consumido) tras el fallo.
    """
    desafio.intentos += 1
    if desafio.intentos >= MAX_INTENTOS:
        desafio.consumido_en = ahora_utc()
        db.flush()
        return True
    db.flush()
    return False


def marcar_verificado(db: Session, desafio: RecuperacionPassword) -> None:
    desafio.verificado_en = ahora_utc()
    db.flush()


def consumir(db: Session, desafio: RecuperacionPassword) -> None:
    desafio.consumido_en = ahora_utc()
    db.flush()
