"""Cifrado en reposo de secretos (contraseñas de activos y semillas TOTP).

Se usa Fernet (AES-128-CBC + HMAC-SHA256, IV aleatorio por mensaje) de la
biblioteca ``cryptography``. La clave vive fuera del repositorio: variable de
entorno ``PASSWD_ENCRYPTION_KEY`` o archivo con permisos 0600 en el
directorio de datos (CIS 3.11 / ISO 27001 A.8.24).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_fernet: Fernet | None = None
_clave_usada: str | None = None


def _obtener_fernet() -> Fernet:
    global _fernet, _clave_usada
    clave = get_settings().encryption_key
    if _fernet is None or _clave_usada != clave:
        _fernet = Fernet(clave.encode("ascii"))
        _clave_usada = clave
    return _fernet


def cifrar(texto_plano: str) -> bytes:
    return _obtener_fernet().encrypt(texto_plano.encode("utf-8"))


def descifrar(datos: bytes) -> str:
    try:
        return _obtener_fernet().decrypt(datos).decode("utf-8")
    except InvalidToken as exc:  # clave incorrecta o datos corruptos
        raise ValueError("No se pudo descifrar: clave de cifrado inválida o datos corruptos.") from exc
