"""Cifrado en reposo de secretos (contraseñas de activos y semillas TOTP).

Se usa Fernet (AES-128-CBC + HMAC-SHA256, IV aleatorio por mensaje) de la
biblioteca ``cryptography``. La clave vive fuera del repositorio: variable de
entorno ``PASSWD_ENCRYPTION_KEY`` o archivo con permisos 0600 en el
directorio de datos (CIS 3.11 / ISO 27001 A.8.24).

Rotación de clave: ``PASSWD_ENCRYPTION_KEY`` admite VARIAS claves separadas
por comas. La primera es la primaria (cifra todo lo nuevo); las demás solo
descifran material antiguo (``MultiFernet``). El procedimiento completo es:
poner ``nueva,antigua`` → ejecutar ``python -m app.cli recifrar`` → dejar
solo ``nueva``. Ver ``docs/referencia-cli.md``.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

_fernet: MultiFernet | None = None
_clave_usada: str | None = None


def _obtener_fernet() -> MultiFernet:
    global _fernet, _clave_usada
    clave = get_settings().encryption_key
    if _fernet is None or _clave_usada != clave:
        claves = [parte.strip() for parte in clave.split(",") if parte.strip()]
        _fernet = MultiFernet([Fernet(parte.encode("ascii")) for parte in claves])
        _clave_usada = clave
    return _fernet


def cifrar(texto_plano: str) -> bytes:
    return _obtener_fernet().encrypt(texto_plano.encode("utf-8"))


def descifrar(datos: bytes) -> str:
    try:
        return _obtener_fernet().decrypt(datos).decode("utf-8")
    except InvalidToken as exc:  # clave incorrecta o datos corruptos
        raise ValueError("No se pudo descifrar: clave de cifrado inválida o datos corruptos.") from exc


def recifrar(datos: bytes) -> bytes:
    """Recifra un blob con la clave primaria (mantiene el texto plano intacto).

    Equivale a ``MultiFernet.rotate``: descifra con cualquiera de las claves
    configuradas y vuelve a cifrar con la primera. Lanza ``ValueError`` si
    ninguna clave puede descifrar los datos.
    """
    try:
        return _obtener_fernet().rotate(datos)
    except InvalidToken as exc:
        raise ValueError("No se pudo recifrar: ninguna clave configurada descifra estos datos.") from exc
