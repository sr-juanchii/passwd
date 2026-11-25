"""Hashing y política de contraseñas.

- Hash con Argon2id (ganador del Password Hashing Competition).
- Política alineada con CIS v8.1 safeguard 5.2: como el MFA es obligatorio
  para todas las cuentas, el mínimo exigido por CIS sería 8; este sistema
  adopta 12 por defecto (configurable) y rechaza contraseñas triviales.
"""

from __future__ import annotations

import secrets
import string
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

# Semilla mínima de contraseñas prohibidas (por si faltara el archivo de datos).
_PROHIBIDAS = {
    "123456789012", "contraseña123", "password1234", "administrador",
    "admin1234567", "qwerty123456", "111111111111", "passwd123456",
}

# Lista amplia empaquetada con la aplicación: las 10 000 contraseñas más
# comunes (SecLists, licencia MIT). La comparación es por igualdad exacta en
# minúsculas — el mínimo de longitud ya descarta casi todas, pero la lista
# cubre las variantes largas y protege si se configura un mínimo menor.
_RUTA_COMUNES = Path(__file__).parent / "data" / "contrasenas-comunes.txt"


@lru_cache(maxsize=1)
def _contrasenas_comunes() -> frozenset[str]:
    comunes = set(_PROHIBIDAS)
    try:
        with _RUTA_COMUNES.open(encoding="utf-8") as archivo:
            comunes.update(linea.strip().lower() for linea in archivo if linea.strip())
    except OSError:
        # Sin el archivo (instalación parcial) se conserva la semilla mínima.
        pass
    return frozenset(comunes)


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
    if password.lower() in _contrasenas_comunes():
        errores.append("Es una contraseña de uso común; elija otra.")
    if username and username.lower() in password.lower():
        errores.append("No debe contener el nombre de usuario.")
    if password.strip() != password:
        errores.append("No debe comenzar ni terminar con espacios.")
    if len(set(password)) < 4:
        errores.append("Debe usar al menos 4 caracteres distintos.")
    return errores


# Alfabeto de las contraseñas que genera el sistema para una rotación por agente.
# Sin espacios, comillas, barras invertidas ni dos puntos: la contraseña viaja
# por la entrada estándar de un helper y acabará copiada a mano alguna vez, y
# cualquiera de esos caracteres es una ocasión de romperla por el camino.
_SIMBOLOS_GENERADOS = "-_.!@#%^*+=?"
_ALFABETO_GENERADO = string.ascii_letters + string.digits + _SIMBOLOS_GENERADOS
LARGO_GENERADO = 20


def generar_password(usuario: str = "", largo: int = LARGO_GENERADO) -> str:
    """Contraseña aleatoria (CSPRNG) que cumple la política vigente.

    Lleva al menos una minúscula, una mayúscula, un dígito y un símbolo, y nunca
    es más corta que el mínimo configurado. Se reintenta hasta que pasa
    ``validar_politica`` (en la práctica, a la primera).
    """
    largo = max(largo, get_settings().password_min_length, 8)
    clases = (string.ascii_lowercase, string.ascii_uppercase, string.digits, _SIMBOLOS_GENERADOS)
    while True:
        caracteres = [secrets.choice(clase) for clase in clases]
        caracteres += [secrets.choice(_ALFABETO_GENERADO) for _ in range(largo - len(clases))]
        # Barajado con el CSPRNG: que la mayúscula no vaya siempre en segundo lugar.
        for i in range(len(caracteres) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            caracteres[i], caracteres[j] = caracteres[j], caracteres[i]
        candidata = "".join(caracteres)
        if not validar_politica(candidata, usuario):
            return candidata
