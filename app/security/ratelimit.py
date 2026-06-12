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


def permitir_intento(clave: str, limite: int | None = None, ventana_minutos: int | None = None) -> bool:
    """True si la clave (IP, usuario…) no superó el límite en la ventana.

    Sin parámetros aplica los valores del inicio de sesión; otros controles
    pasan su propio límite y ventana (p. ej. revelado de credenciales).
    """
    settings = get_settings()
    if limite is None:
        limite = settings.login_rate_limit
    if ventana_minutos is None:
        ventana_minutos = settings.login_rate_window_minutes
    ventana = ventana_minutos * 60
    ahora = time.monotonic()
    with _lock:
        cola = _eventos[clave]
        while cola and ahora - cola[0] > ventana:
            cola.popleft()
        if len(cola) >= limite:
            return False
        cola.append(ahora)
        return True


def reiniciar() -> None:
    """Limpia el estado (uso exclusivo en pruebas)."""
    with _lock:
        _eventos.clear()
