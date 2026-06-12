"""Códigos de recuperación MFA de un solo uso.

Permiten completar el segundo factor si el usuario pierde su dispositivo
autenticador. Se generan al enrolar el MFA, se muestran una sola vez y solo
se persiste su hash SHA-256. Cada código se invalida al usarse.
"""

from __future__ import annotations

import hashlib
import re
import secrets

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CodigoRecuperacionMFA, Usuario, ahora_utc

CANTIDAD_CODIGOS = 8
# Alfabeto sin caracteres ambiguos (0/O, 1/I/L)
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_GRUPOS = 2
_LARGO_GRUPO = 5


def _normalizar(codigo: str) -> str:
    return re.sub(r"[^A-Z2-9]", "", codigo.upper())


def _hash(codigo: str) -> str:
    return hashlib.sha256(_normalizar(codigo).encode("ascii")).hexdigest()


def _generar_codigo() -> str:
    grupos = [
        "".join(secrets.choice(_ALFABETO) for _ in range(_LARGO_GRUPO))
        for _ in range(_GRUPOS)
    ]
    return "-".join(grupos)


def emitir_codigos(db: Session, usuario: Usuario) -> list[str]:
    """Invalida los códigos anteriores y emite un juego nuevo en claro."""
    db.execute(delete(CodigoRecuperacionMFA).where(CodigoRecuperacionMFA.usuario_id == usuario.id))
    codigos = [_generar_codigo() for _ in range(CANTIDAD_CODIGOS)]
    for codigo in codigos:
        db.add(CodigoRecuperacionMFA(usuario_id=usuario.id, codigo_hash=_hash(codigo)))
    db.flush()
    return codigos


def consumir_codigo(db: Session, usuario: Usuario, intento: str) -> bool:
    """Marca el código como usado si es válido; False en caso contrario."""
    if len(_normalizar(intento)) != _GRUPOS * _LARGO_GRUPO:
        return False
    registro = db.scalar(
        select(CodigoRecuperacionMFA).where(
            CodigoRecuperacionMFA.usuario_id == usuario.id,
            CodigoRecuperacionMFA.codigo_hash == _hash(intento),
            CodigoRecuperacionMFA.usado_en.is_(None),
        )
    )
    if registro is None:
        return False
    registro.usado_en = ahora_utc()
    db.flush()
    return True


def codigos_restantes(db: Session, usuario: Usuario) -> int:
    return len(
        db.scalars(
            select(CodigoRecuperacionMFA.id).where(
                CodigoRecuperacionMFA.usuario_id == usuario.id,
                CodigoRecuperacionMFA.usado_en.is_(None),
            )
        ).all()
    )


def eliminar_codigos(db: Session, usuario_id: int) -> None:
    db.execute(delete(CodigoRecuperacionMFA).where(CodigoRecuperacionMFA.usuario_id == usuario_id))
