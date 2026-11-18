"""Reautenticación para acciones de alto impacto.

«Mi seguridad» ya pide contraseña + segundo factor para cambiar el método MFA.
La autorización de una rotación necesita lo mismo, con una diferencia
deliberada: **no admite el código por correo**.

Un OTP enviado al buzón no es una segunda persona ni un segundo factor
independiente. El buzón puede ser compartido por el equipo de sistemas, estar
abierto en la misma sesión del navegador o ser accesible para quien ya controla
la cuenta. Toda la regla de dos pares de la gobernanza de rotación descansa en
que el autorizador demuestre posesión de algo que el solicitante no tiene, y el
correo no da esa garantía. Ver ``docs/resistencia-bypass-mfa.md``.

Los códigos de recuperación sí se admiten: son de un solo uso, se entregan al
titular en el enrolamiento y acreditan posesión igual que la aplicación
autenticadora. Es el mismo criterio que ya aplica el cambio de método de
segundo factor.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import MFA_TOTP, Usuario
from app.security import recovery, segundo_factor
from app.security.passwords import verificar_password


class ErrorReautenticacion(Exception):
    """La reautenticación no se superó. ``codigo`` es el HTTP que corresponde."""

    def __init__(self, mensaje: str, codigo: int = 403) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


def reautenticar(db: Session, usuario: Usuario, password: str, codigo: str) -> None:
    """Exige contraseña y segundo factor **sin correo**. Lanza si no se cumple.

    No distingue en el mensaje si falló la contraseña o el código: decirlo
    convertiría esta pantalla en un oráculo para comprobar contraseñas de
    administrador desde una sesión ya abierta.
    """
    if not password or not codigo:
        raise ErrorReautenticacion(
            "Para autorizar esta acción debe confirmar su contraseña y un código "
            "de su aplicación autenticadora.", codigo=400,
        )
    if usuario.mfa_metodo != MFA_TOTP and recovery.codigos_restantes(db, usuario) == 0:
        raise ErrorReautenticacion(
            "Esta acción exige una aplicación autenticadora. El código por correo no "
            "sirve para autorizar una rotación: configure el segundo factor en «Mi "
            "seguridad» antes de autorizar.",
        )
    password_ok = verificar_password(usuario.password_hash, password)
    resultado = segundo_factor.comprobar(db, usuario, codigo, permitir_correo=False)
    if not (password_ok and resultado.valido):
        raise ErrorReautenticacion(
            "No se pudo confirmar su identidad. Revise la contraseña y el código "
            "de su aplicación autenticadora.",
        )
