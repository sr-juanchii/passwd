"""Excepciones propias de la aplicación."""

from __future__ import annotations


class RedirigirLogin(Exception):
    """Señal interna: la petición debe redirigirse a la pantalla de acceso."""

    def __init__(self, destino: str = "/login") -> None:
        self.destino = destino
