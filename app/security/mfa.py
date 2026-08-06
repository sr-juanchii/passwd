"""Autenticación multifactor con TOTP (RFC 6238).

Cumple CIS v8.1 safeguards 6.3/6.4/6.5: MFA obligatorio para todas las
cuentas de la aplicación, incluidas las administrativas. El secreto TOTP se
almacena cifrado y el código QR se genera en el servidor (SVG embebido),
sin depender de servicios externos.
"""

from __future__ import annotations

import base64
import io

import pyotp
import segno

from app.config import get_settings


def generar_secreto() -> str:
    return pyotp.random_base32()


def uri_aprovisionamiento(secreto: str, username: str) -> str:
    issuer = get_settings().totp_issuer
    return pyotp.TOTP(secreto).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg_data_uri(secreto: str, username: str) -> str:
    """Código QR del URI otpauth:// como data-URI SVG para incrustar en HTML."""
    qr = segno.make(uri_aprovisionamiento(secreto, username), error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=4, dark="#1a1a2e", border=2)
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def normalizar_codigo(codigo: str) -> str:
    """Forma canónica de un código TOTP: dígitos sin espacios ni separadores.

    ÚNICO punto de normalización del proyecto, y debe usarse tanto al VALIDAR un
    código como al REGISTRARLO en ``Usuario.ultimo_otp_usado`` para impedir su
    reutilización (RFC 6238 §5.2).

    Que ambas operaciones compartan esta función no es cosmético: si la
    validación normalizara los espacios y el registro no, el mismo código pasaría
    dos veces con solo reformatearlo (p. ej. «123 456» frente a «123456»), porque
    la comparación anti-reutilización no reconocería la forma almacenada. Las
    aplicaciones autenticadoras muestran los códigos agrupados —«123 456»—, así
    que la forma con espacio llega al servidor de manera habitual, no excepcional.
    Además, la forma canónica cabe siempre en la columna ``String(8)``, mientras
    que una sin normalizar («1 2 3 4 5 6») se truncaría o desbordaría.
    """
    return codigo.strip().replace(" ", "")


def verificar_codigo(secreto: str, codigo: str) -> bool:
    codigo = normalizar_codigo(codigo)
    if not codigo.isdigit() or len(codigo) != 6:
        return False
    # valid_window=1 tolera un desfase de reloj de ±30 s
    return pyotp.TOTP(secreto).verify(codigo, valid_window=1)
