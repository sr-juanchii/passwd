"""OTP de un solo uso por correo, como método de respaldo del MFA.

Cubre el caso operativo de un usuario que no tiene acceso a su aplicación
autenticadora (dispositivo perdido, cambiado o sin batería) ni a sus códigos de
recuperación: puede pedir un código a su buzón registrado y completar el segundo
factor con él.

Posición en el modelo de seguridad
----------------------------------
Este factor es **más débil que el TOTP** y conviene tenerlo presente: quien
controle el buzón del usuario y conozca su contraseña completa la autenticación.
El correo no está bajo la custodia de esta aplicación (buzones ajenos, reenvíos,
copias en servidores intermedios), así que añade una dependencia externa a la
cadena de acceso. Por eso:

* Es **desactivable** con ``PASSWD_EMAIL_OTP_ENABLED=false`` (también en caliente
  desde la consola de configuración), sin tocar el resto del MFA.
* Solo se puede pedir desde la etapa ``mfa_pendiente``: exige la contraseña
  válida primero, nunca es un punto de entrada por sí solo.
* Cada uso queda **auditado** y dispara además una alerta a la lista de seguridad
  (``PASSWD_NOTIFY_TO``), porque un acceso por esta vía merece revisión.
* Códigos de 8 dígitos, un solo uso, caducidad corta y tope de intentos.

El orden de preferencia recomendado sigue siendo: TOTP → códigos de recuperación
→ OTP por correo. Ver ``docs/notificaciones-y-mfa-correo.md``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CodigoOtpCorreo, Usuario, ahora_utc

# 8 dígitos: 10^8 combinaciones. Con MAX_INTENTOS=5 por código y el bloqueo de
# cuenta del flujo de MFA, la fuerza bruta es inviable.
LARGO_CODIGO = 8
MAX_INTENTOS = 5


def habilitado() -> bool:
    """¿Está disponible el OTP por correo?

    Exige el interruptor propio y que el correo esté operativo: sin SMTP el
    código no podría entregarse, así que ofrecerlo sería engañoso.
    """
    from app.notifications import correo_operativo

    return bool(get_settings().email_otp_enabled and correo_operativo())


def _hash(codigo: str) -> str:
    return hashlib.sha256(normalizar(codigo).encode("ascii")).hexdigest()


def normalizar(codigo: str) -> str:
    """Forma canónica del código: dígitos sin espacios ni separadores.

    Único punto de normalización, usado tanto al emitir como al verificar. La
    misma lección que en ``app/security/mfa.py``: si el registro y la comparación
    normalizaran distinto, el control de un solo uso se podría eludir cambiando el
    formato del código.
    """
    return "".join(c for c in (codigo or "") if c.isdigit())


def _generar_codigo() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(LARGO_CODIGO))


def invalidar_codigos(db: Session, usuario_id: int) -> None:
    """Invalida los códigos vivos del usuario (al emitir uno nuevo o al entrar)."""
    db.execute(
        update(CodigoOtpCorreo)
        .where(
            CodigoOtpCorreo.usuario_id == usuario_id,
            CodigoOtpCorreo.usado_en.is_(None),
            CodigoOtpCorreo.invalidado_en.is_(None),
        )
        .values(invalidado_en=ahora_utc())
    )


def emitir(db: Session, usuario: Usuario, direccion_ip: str = "") -> str:
    """Emite un código nuevo (invalidando los anteriores) y lo devuelve en claro.

    El valor en claro solo se usa para redactar el correo; en base de datos queda
    únicamente su hash SHA-256.
    """
    invalidar_codigos(db, usuario.id)
    codigo = _generar_codigo()
    registro = CodigoOtpCorreo(
        usuario_id=usuario.id,
        codigo_hash=_hash(codigo),
        expira_en=ahora_utc() + timedelta(minutes=get_settings().email_otp_ttl_minutes),
        direccion_ip=(direccion_ip or "")[:45],
    )
    db.add(registro)
    db.flush()
    return codigo


def consumir(db: Session, usuario: Usuario, intento: str) -> bool:
    """Valida y consume un código. True solo si era correcto y estaba vigente.

    Suma un intento fallido al código vivo cuando el valor no coincide y lo
    invalida al alcanzar ``MAX_INTENTOS``, de modo que un código concreto no se
    puede sondear indefinidamente. La comparación del hash se hace en tiempo
    constante.
    """
    limpio = normalizar(intento)
    if len(limpio) != LARGO_CODIGO:
        return False

    registro = db.scalar(
        select(CodigoOtpCorreo)
        .where(
            CodigoOtpCorreo.usuario_id == usuario.id,
            CodigoOtpCorreo.usado_en.is_(None),
            CodigoOtpCorreo.invalidado_en.is_(None),
        )
        .order_by(CodigoOtpCorreo.creado_en.desc())
    )
    if registro is None:
        return False
    if not registro.vigente:
        registro.invalidado_en = ahora_utc()
        db.flush()
        return False

    if not hmac.compare_digest(registro.codigo_hash, _hash(limpio)):
        registro.intentos += 1
        if registro.intentos >= MAX_INTENTOS:
            registro.invalidado_en = ahora_utc()
        db.flush()
        return False

    registro.usado_en = ahora_utc()
    db.flush()
    return True


def purgar_expirados(db: Session, dias: int = 7) -> int:
    """Elimina códigos consumidos o caducados hace más de ``dias`` (higiene)."""
    from sqlalchemy import delete

    corte = ahora_utc() - timedelta(days=dias)
    resultado = db.execute(delete(CodigoOtpCorreo).where(CodigoOtpCorreo.expira_en < corte))
    return int(resultado.rowcount or 0)


def texto_correo(usuario: Usuario, codigo: str, direccion_ip: str) -> tuple[str, str]:
    """Asunto y cuerpo del correo con el código. El código ES el contenido aquí."""
    minutos = get_settings().email_otp_ttl_minutes
    asunto = "Código de verificación de acceso"
    cuerpo = (
        f"Se solicitó un código de verificación para completar el acceso de la "
        f"cuenta «{usuario.username}».\n\n"
        f"    CÓDIGO:  {codigo}\n\n"
        f"Caduca en {minutos} minutos y solo puede usarse UNA vez.\n\n"
        f"  Solicitado desde la IP: {direccion_ip or 'desconocida'}\n"
        f"  Fecha y hora (UTC):     {ahora_utc():%Y-%m-%d %H:%M:%S}\n\n"
        "Si NO fue usted quien lo solicitó, alguien conoce su contraseña: cambie "
        "su contraseña de inmediato y avise al administrador. No comparta este "
        "código con nadie, ni siquiera con personal de soporte.\n\n"
        "---\n"
        "Aviso automático del Gestor de Contraseñas de Servidores."
    )
    return asunto, cuerpo
