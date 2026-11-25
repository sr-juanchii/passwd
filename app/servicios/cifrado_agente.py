"""Cifrado de un trabajo hacia el agente que lo ejecutará (v1.4.0).

Cada agente genera su par **X25519** al enrolarse y entrega la clave pública.
Al servirle un trabajo, el backend lo **sella** a esa clave:

    efímera X25519 del backend  ×  clave pública del agente   →  secreto compartido
    HKDF-SHA256(secreto, salt = efímera_pub ‖ agente_pub,
                info = "passwd-agente/trabajo/v1")              →  32 bytes
    Fernet(esos 32 bytes)                                       →  token

El sobre que viaja es ``{"v": 1, "efimera": <b64>, "token": <fernet>}``. Solo el
dueño de la clave privada lo abre: un token de agente robado sin su clave
privada no basta para leer un trabajo, y la contraseña viaja protegida también
por dentro de TLS.

**Qué NO protege** (docs/plan-rotacion-agentes.md H14): el sellado es para la
ENTREGA. En reposo el trabajo se guarda con el Fernet del backend, igual que
cualquier credencial, porque cuando el agente confirma ``aplicado`` el backend
tiene que escribir esa contraseña y no tiene la clave privada del agente. Y un
backend comprometido entero ya tiene todas las contraseñas (§4.1).

Solo primitivas de ``cryptography``; ningún esquema propio. El agente Go
implementa exactamente lo mismo, y los vectores de
``tests/vectores/cifrado_agente.json`` prueban que ambos lados coinciden.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION_SOBRE = 1
INFO_HKDF = b"passwd-agente/trabajo/v1"
_LARGO_CLAVE = 32


class ErrorCifradoAgente(ValueError):
    """Clave o sobre inválidos. El mensaje nunca contiene material secreto."""


def _crudo(clave: X25519PublicKey) -> bytes:
    return clave.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def decodificar_clave_publica(clave_publica_b64: str) -> bytes:
    """Clave pública X25519 en crudo (32 bytes) a partir de su base64 estándar."""
    try:
        cruda = base64.b64decode((clave_publica_b64 or "").strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErrorCifradoAgente("La clave pública del agente no es base64 válido.") from exc
    if len(cruda) != _LARGO_CLAVE:
        raise ErrorCifradoAgente("La clave pública del agente debe ser X25519 (32 bytes).")
    return cruda


def validar_clave_publica(clave_publica_b64: str) -> str:
    """Devuelve la clave normalizada (base64 estándar) o lanza ``ErrorCifradoAgente``."""
    return _b64(decodificar_clave_publica(clave_publica_b64))


def huella(clave_publica_b64: str) -> str:
    """SHA-256 hexadecimal de la clave pública en crudo: identifica el par usado."""
    return hashlib.sha256(decodificar_clave_publica(clave_publica_b64)).hexdigest()


def _clave_fernet(compartido: bytes, efimera_pub: bytes, agente_pub: bytes) -> Fernet:
    derivada = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=efimera_pub + agente_pub, info=INFO_HKDF,
    ).derive(compartido)
    return Fernet(base64.urlsafe_b64encode(derivada))


def sellar(clave_publica_b64: str, contenido: dict) -> dict:
    """Sella ``contenido`` (JSON) para el dueño de la clave privada correspondiente."""
    agente_pub = decodificar_clave_publica(clave_publica_b64)
    efimera = X25519PrivateKey.generate()
    efimera_pub = _crudo(efimera.public_key())
    compartido = efimera.exchange(X25519PublicKey.from_public_bytes(agente_pub))
    token = _clave_fernet(compartido, efimera_pub, agente_pub).encrypt(
        json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return {"v": VERSION_SOBRE, "efimera": _b64(efimera_pub), "token": token.decode("ascii")}


def abrir(clave_privada: X25519PrivateKey, sobre: dict) -> dict:
    """Abre un sobre. Lo usa el agente; aquí sirve de referencia y para las pruebas."""
    if not isinstance(sobre, dict) or sobre.get("v") != VERSION_SOBRE:
        raise ErrorCifradoAgente("Versión de sobre desconocida.")
    try:
        efimera_pub = base64.b64decode(sobre["efimera"], validate=True)
        token = str(sobre["token"]).encode("ascii")
    except (KeyError, binascii.Error, ValueError) as exc:
        raise ErrorCifradoAgente("Sobre mal formado.") from exc
    if len(efimera_pub) != _LARGO_CLAVE:
        raise ErrorCifradoAgente("Sobre mal formado.")
    agente_pub = _crudo(clave_privada.public_key())
    compartido = clave_privada.exchange(X25519PublicKey.from_public_bytes(efimera_pub))
    try:
        claro = _clave_fernet(compartido, efimera_pub, agente_pub).decrypt(token)
    except InvalidToken as exc:
        raise ErrorCifradoAgente("El sobre no se abre con esta clave.") from exc
    return json.loads(claro)
