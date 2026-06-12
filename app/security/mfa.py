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


def verificar_codigo(secreto: str, codigo: str) -> bool:
    codigo = codigo.strip().replace(" ", "")
    if not codigo.isdigit() or len(codigo) != 6:
        return False
    # valid_window=1 tolera un desfase de reloj de ±30 s
    return pyotp.TOTP(secreto).verify(codigo, valid_window=1)
