"""Segundo factor: política de métodos y comprobación única del código.

Cada usuario tiene un **método principal** (``Usuario.mfa_metodo``):

* ``totp``   — aplicación autenticadora (Google Authenticator, Authy…).
* ``correo`` — código de un solo uso enviado a su buzón registrado.

Además, todos disponen de códigos de recuperación, y quien usa TOTP puede pedir
un código por correo como **respaldo** si el administrador lo permite.

Este módulo es el ÚNICO punto que decide qué métodos puede usar un usuario y que
comprueba un código de segundo factor. Lo comparten la API JSON y la interfaz
clásica para que las reglas no puedan divergir.

El correo es un factor más débil que el TOTP (depende de la seguridad del
buzón), por eso su uso como método principal es una decisión del administrador
(``email_otp_primary_enabled``) y por defecto no se admite para administradores
(``mfa_totp_required_admin``).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MFA_CORREO, MFA_TOTP, ROL_ADMIN, Usuario
from app.security import mfa, otp_correo, recovery
from app.security.crypto import descifrar

VIA_TOTP = "totp"
VIA_RECUPERACION = "recuperacion"
VIA_CORREO = "correo"


def _correo_operativo() -> bool:
    from app.notifications import correo_operativo

    return correo_operativo()


def correo_principal_por_politica(usuario: Usuario) -> bool:
    """¿La política permite a este usuario tener el correo como método principal?

    No mira si el correo funciona ahora mismo: es la regla, no la disponibilidad.
    """
    settings = get_settings()
    if not settings.email_otp_primary_enabled:
        return False
    return not (usuario.rol == ROL_ADMIN and settings.mfa_totp_required_admin)


def correo_principal_disponible(usuario: Usuario) -> bool:
    """¿Puede este usuario ELEGIR hoy el correo como método principal?"""
    return correo_principal_por_politica(usuario) and _correo_operativo()


def motivo_correo_no_disponible(usuario: Usuario) -> str:
    """Explicación para la interfaz de por qué no se ofrece el correo."""
    settings = get_settings()
    if not settings.email_otp_primary_enabled:
        return "El administrador no ha habilitado el código por correo como método principal."
    if usuario.rol == ROL_ADMIN and settings.mfa_totp_required_admin:
        return "Las cuentas de administrador deben usar una aplicación autenticadora."
    if not _correo_operativo():
        return "El servicio de correo no está configurado en este momento."
    return ""


def metodos_enrolables(usuario: Usuario) -> list[str]:
    """Métodos entre los que el usuario puede elegir al enrolarse."""
    metodos = [MFA_TOTP]
    if correo_principal_disponible(usuario):
        metodos.append(MFA_CORREO)
    return metodos


def correo_en_login(usuario: Usuario) -> bool:
    """¿Puede este usuario pedir un código por correo para completar el acceso?

    Como método principal basta con que el correo funcione (la cuenta ya se
    enroló así); como respaldo de TOTP depende además de ``email_otp_enabled``.
    """
    if usuario.mfa_metodo == MFA_CORREO:
        return _correo_operativo()
    return otp_correo.habilitado()


def debe_reenrolar_con_totp(usuario: Usuario) -> bool:
    """Una cuenta enrolada por correo que ya no puede usarlo como principal
    (cambió la política o pasó a ser administradora) debe configurar TOTP."""
    return usuario.mfa_metodo == MFA_CORREO and not correo_principal_por_politica(usuario)


def aceptar_totp(usuario: Usuario, codigo: str) -> tuple[bool, bool]:
    """Valida un TOTP y, si es correcto, lo registra como usado.

    Devuelve ``(valido, reutilizado)``. Un código de un paso temporal igual o
    anterior al último aceptado se rechaza como reutilizado.
    """
    if usuario.totp_secret_cifrado is None:
        return False, False
    limpio = mfa.normalizar_codigo(codigo)
    paso = mfa.paso_de_codigo(descifrar(usuario.totp_secret_cifrado), codigo)
    if paso is None:
        return False, False
    if usuario.ultimo_totp_paso is not None and paso <= usuario.ultimo_totp_paso:
        return False, True
    # Cuentas anteriores a ``ultimo_totp_paso``: se conserva la comparación literal.
    if usuario.ultimo_totp_paso is None and usuario.ultimo_otp_usado == limpio:
        return False, True
    usuario.ultimo_totp_paso = paso
    usuario.ultimo_otp_usado = limpio
    return True, False


@dataclass(frozen=True)
class Resultado:
    via: str | None  # VIA_* si el código fue aceptado; None si no
    reutilizado: bool = False

    @property
    def valido(self) -> bool:
        return self.via is not None

    @property
    def correo_como_respaldo(self) -> bool:
        return self.via == VIA_CORREO


def comprobar(db: Session, usuario: Usuario, codigo: str, *, permitir_correo: bool = True) -> Resultado:
    """Comprueba un código de segundo factor contra todos los métodos del usuario.

    Orden: TOTP (si es su método) → código de recuperación → código por correo.
    Los códigos aceptados quedan consumidos (un solo uso).
    """
    reutilizado = False
    if usuario.mfa_metodo == MFA_TOTP:
        valido, reutilizado = aceptar_totp(usuario, codigo)
        if valido:
            return Resultado(VIA_TOTP)
    if recovery.consumir_codigo(db, usuario, codigo):
        return Resultado(VIA_RECUPERACION)
    if permitir_correo and correo_en_login(usuario) and otp_correo.consumir(db, usuario, codigo):
        otp_correo.invalidar_codigos(db, usuario.id)
        return Resultado(VIA_CORREO)
    return Resultado(None, reutilizado)
