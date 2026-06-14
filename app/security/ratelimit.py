"""Limitación de tasa en memoria.

Complementa el bloqueo de cuenta persistente: frena la enumeración de
usuarios y la fuerza bruta por IP en el inicio de sesión, y limita el
volumen de revelados/copiados de contraseñas por usuario (anti-exfiltración,
OWASP API4/API6).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import get_settings

_lock = threading.Lock()
_eventos: dict[str, deque[float]] = defaultdict(deque)


def permitir_intento(clave: str, limite: int | None = None, ventana_minutos: int | None = None, db=None) -> bool:
    """True si la clave (IP, usuario…) no superó el límite en la ventana.

    Backend en memoria (un proceso) por defecto, o en BD (compartido entre
    instancias) si ``PASSWD_RATE_LIMIT_BACKEND=bd`` y se proporciona ``db``.
    """
    settings = get_settings()
    if limite is None:
        limite = settings.login_rate_limit
    if ventana_minutos is None:
        ventana_minutos = settings.login_rate_window_minutes

    if settings.rate_limit_backend == "bd" and db is not None:
        return _permitir_bd(db, clave, limite, ventana_minutos)
    return _permitir_memoria(clave, limite, ventana_minutos * 60)


def _permitir_memoria(clave: str, limite: int, ventana_seg: int) -> bool:
    ahora = time.monotonic()
    with _lock:
        cola = _eventos[clave]
        while cola and ahora - cola[0] > ventana_seg:
            cola.popleft()
        if len(cola) >= limite:
            return False
        cola.append(ahora)
        return True


def _permitir_bd(db, clave: str, limite: int, ventana_minutos: int) -> bool:
    from datetime import timedelta

    from sqlalchemy import delete, func, select

    from app.models import EventoTasa, ahora_utc

    corte = ahora_utc() - timedelta(minutes=ventana_minutos)
    db.execute(delete(EventoTasa).where(EventoTasa.clave == clave, EventoTasa.momento < corte))
    actuales = db.scalar(
        select(func.count(EventoTasa.id)).where(EventoTasa.clave == clave, EventoTasa.momento >= corte)
    ) or 0
    if actuales >= limite:
        return False
    db.add(EventoTasa(clave=clave, momento=ahora_utc()))
    db.flush()
    return True


def reiniciar() -> None:
    """Limpia el estado (uso exclusivo en pruebas)."""
    with _lock:
        _eventos.clear()
