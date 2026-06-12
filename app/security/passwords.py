"""Hashing y política de contraseñas.

- Hash con Argon2id (ganador del Password Hashing Competition).
- Política alineada con CIS v8.1 safeguard 5.2: como el MFA es obligatorio
  para todas las cuentas, el mínimo exigido por CIS sería 8; este sistema
  adopta 12 por defecto (configurable) y rechaza contraseñas triviales.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

# Lista corta de contraseñas prohibidas por ser de uso masivo.
_PROHIBIDAS = {
    "123456789012", "contraseña123", "password1234", "administrador",
    "admin1234567", "qwerty123456", "111111111111", "passwd123456",
}


def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(hash_almacenado: str, password: str) -> bool:
    try:
        return _hasher.verify(hash_almacenado, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def necesita_rehash(hash_almacenado: str) -> bool:
    return _hasher.check_needs_rehash(hash_almacenado)


def validar_politica(password: str, username: str = "") -> list[str]:
    """Devuelve la lista de incumplimientos de la política (vacía si es válida)."""
    minimo = get_settings().password_min_length
    errores: list[str] = []
    if len(password) < minimo:
        errores.append(f"Debe tener al menos {minimo} caracteres.")
    if password.lower() in _PROHIBIDAS:
        errores.append("Es una contraseña de uso común; elija otra.")
    if username and username.lower() in password.lower():
        errores.append("No debe contener el nombre de usuario.")
    if password.strip() != password:
        errores.append("No debe comenzar ni terminar con espacios.")
    if len(set(password)) < 4:
        errores.append("Debe usar al menos 4 caracteres distintos.")
    return errores
