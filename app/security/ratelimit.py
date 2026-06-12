"""Limitación de tasa en memoria para el inicio de sesión.

Complementa el bloqueo de cuenta persistente: frena la enumeración de
usuarios y los ataques de fuerza bruta distribuidos por IP de origen.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import get_settings

_lock = threading.Lock()
_eventos: dict[str, deque[float]] = defaultdict(deque)


def permitir_intento(clave: str) -> bool:
    """True si la clave (p. ej. la IP) no superó el límite en la ventana."""
    settings = get_settings()
    ventana = settings.login_rate_window_minutes * 60
    ahora = time.monotonic()
    with _lock:
        cola = _eventos[clave]
        while cola and ahora - cola[0] > ventana:
            cola.popleft()
        if len(cola) >= settings.login_rate_limit:
            return False
        cola.append(ahora)
        return True


def reiniciar() -> None:
    """Limpia el estado (uso exclusivo en pruebas)."""
    with _lock:
        _eventos.clear()
