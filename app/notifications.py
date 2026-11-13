"""Correo saliente: servicio SMTP, alertas y avisos (opt-in).

El **servicio de correo** (``smtp_enabled`` + servidor SMTP) es la base de todo
lo que la aplicación envía. Sobre él hay dos familias de destinatario, cada una
con su propio interruptor:

1. **Estática** (``enviar_alerta``): a la lista fija ``PASSWD_NOTIFY_TO``, para
   eventos de plataforma que interesan al equipo de seguridad (cuenta bloqueada,
   posible exfiltración, fallo de respaldo).
2. **Dinámica** (``enviar_a_usuario`` / ``enviar_a_usuarios``): al correo de cada
   usuario afectado, resuelto en tiempo de ejecución desde su matriz de permisos
   (ver ``app.avisos``). Cubre la actividad de la propia sesión, los cambios en
   los permisos propios, las modificaciones de credenciales compartidas y los
   avisos de caducidad de rotación.

Los mensajes **nunca** contienen contraseñas de servidores ni otros secretos del
inventario: solo el hecho y su contexto. La única excepción deliberada es la
contraseña TEMPORAL de un restablecimiento administrativo y el código OTP de
respaldo del MFA, que por definición viajan al buzón de su titular y son de un
solo uso y corta vida (ver ``docs/notificaciones-y-mfa-correo.md``).

El envío es de mejor esfuerzo: un fallo de SMTP se registra pero nunca rompe
el flujo principal de la aplicación.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from email.message import EmailMessage

from app.config import SMTP_SSL, SMTP_STARTTLS, get_settings

logger = logging.getLogger("passwd.notify")

_TIMEOUT = 10  # segundos por operación de red


def _destinatarios(settings) -> list[str]:
    return [d.strip() for d in settings.notify_to.split(",") if d.strip()]


def _remitente(settings) -> str:
    return (settings.smtp_from or settings.smtp_user or "").strip()


def _conectar(settings) -> smtplib.SMTP:
    """Abre la conexión SMTP según el modo de cifrado y autentica si hay usuario.

    * ``ssl``      — TLS implícito desde el primer byte (puerto 465 habitual).
    * ``starttls`` — conexión en claro que se eleva a TLS (puerto 587 habitual).
    * ``ninguna``  — sin cifrado: solo para relés internos de confianza.
    """
    if settings.smtp_security == SMTP_SSL:
        servidor: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT,
            context=ssl.create_default_context())
    else:
        servidor = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT)
    try:
        if settings.smtp_security == SMTP_STARTTLS:
            servidor.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            servidor.login(settings.smtp_user, settings.smtp_password)
    except Exception:
        servidor.close()
        raise
    return servidor


def _enviar_smtp(settings, destinatarios: list[str], asunto: str, cuerpo: str) -> None:
    mensaje = EmailMessage()
    mensaje["Subject"] = f"[{settings.totp_issuer}] {asunto}"
    mensaje["From"] = _remitente(settings)
    mensaje["To"] = ", ".join(destinatarios)
    mensaje.set_content(cuerpo)

    with _conectar(settings) as servidor:
        servidor.send_message(mensaje)


def enviar_alerta(asunto: str, cuerpo: str) -> bool:
    """Envía una alerta si las notificaciones están configuradas. No lanza."""
    settings = get_settings()
    destinatarios = _destinatarios(settings)
    if not correo_operativo() or not settings.notify_enabled or not destinatarios:
        return False
    try:
        _enviar_smtp(settings, destinatarios, asunto, cuerpo)
        return True
    except Exception:  # noqa: BLE001 — el aviso es de mejor esfuerzo
        logger.exception("No se pudo enviar la alerta por correo: %s", asunto)
        return False


def correo_operativo() -> bool:
    """¿Puede la aplicación enviar correo? Servicio activo y servidor definido.

    Es la condición de TODO lo que depende del correo (código del segundo factor,
    contraseñas temporales, alertas y avisos). Las alertas a administradores y
    los avisos a usuarios tienen además su propio interruptor.
    """
    settings = get_settings()
    return bool(settings.smtp_enabled and settings.smtp_host)


def enviar_a_direccion(destinatario: str, asunto: str, cuerpo: str) -> bool:
    """Envía un aviso a una dirección concreta. Mejor esfuerzo: no lanza."""
    destinatario = (destinatario or "").strip()
    if not destinatario or not correo_operativo():
        return False
    try:
        _enviar_smtp(get_settings(), [destinatario], asunto, cuerpo)
        return True
    except Exception:  # noqa: BLE001 — el aviso es de mejor esfuerzo
        logger.exception("No se pudo enviar el aviso «%s» a un destinatario", asunto)
        return False


def enviar_a_usuario(usuario, asunto: str, cuerpo: str) -> bool:
    """Envía un aviso al correo de un usuario activo. Mejor esfuerzo: no lanza."""
    if usuario is None or not getattr(usuario, "activo", False):
        return False
    return enviar_a_direccion(getattr(usuario, "email", ""), asunto, cuerpo)


def enviar_a_usuarios(usuarios, asunto: str, cuerpo: str) -> int:
    """Envía el MISMO aviso a varios usuarios, uno por mensaje.

    Se manda un correo independiente por destinatario a propósito: agrupar las
    direcciones en un solo ``To:`` revelaría a cada usuario quién más tiene
    acceso al activo, que es justamente información de control de acceso. Además
    se deduplican direcciones repetidas. Devuelve cuántos envíos salieron bien.
    """
    if not correo_operativo():
        return 0
    enviados = 0
    ya_enviado: set[str] = set()
    for usuario in usuarios:
        direccion = (getattr(usuario, "email", "") or "").strip().lower()
        if not direccion or direccion in ya_enviado:
            continue
        ya_enviado.add(direccion)
        if enviar_a_usuario(usuario, asunto, cuerpo):
            enviados += 1
    return enviados


class ErrorCorreo(Exception):
    """Fallo al enviar un correo de prueba (mensaje apto para mostrar)."""


def _explicar(exc: Exception) -> str:
    """Traduce un fallo SMTP a un mensaje útil y sin datos internos.

    El detalle completo queda en el log del servidor; a la interfaz solo llega
    una causa probable con la pista de qué ajuste revisar.
    """
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "El servidor rechazó el usuario o la contraseña SMTP."
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return ("El servidor no admite lo solicitado (STARTTLS o autenticación). "
                "Revise el modo de seguridad y si el servidor exige usuario.")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "El servidor rechazó la dirección del destinatario."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "El servidor rechazó el remitente. Revise la dirección «Remitente»."
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "El certificado TLS del servidor no es válido para ese nombre de host."
    if isinstance(exc, ssl.SSLError):
        return ("No se pudo negociar el cifrado. Compruebe que el modo de seguridad "
                "corresponde al puerto (SSL/TLS → 465, STARTTLS → 587).")
    if isinstance(exc, socket.gaierror):
        return "No se encontró el servidor SMTP. Revise el nombre del host."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "El servidor SMTP no respondió a tiempo. Revise host, puerto y cortafuegos."
    if isinstance(exc, ConnectionRefusedError):
        return "El servidor rechazó la conexión. Revise el puerto."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return ("El servidor cerró la conexión. Suele indicar un modo de seguridad "
                "que no corresponde al puerto.")
    if isinstance(exc, smtplib.SMTPResponseException):
        return f"El servidor SMTP respondió con un error (código {exc.smtp_code})."
    if isinstance(exc, OSError):
        return "No se pudo conectar con el servidor SMTP. Revise host y puerto."
    return "Error inesperado al hablar con el servidor SMTP."


def probar_conexion(settings=None) -> str:
    """Conecta, negocia el cifrado y autentica, SIN enviar ningún mensaje.

    ``settings`` permite probar valores aún no guardados (los del formulario).
    Devuelve una descripción del resultado o lanza ``ErrorCorreo``.
    """
    s = settings if settings is not None else get_settings()
    if not s.smtp_host:
        raise ErrorCorreo("Indique el servidor SMTP.")
    try:
        with _conectar(s) as servidor:
            servidor.noop()
    except Exception as exc:  # noqa: BLE001 — se traduce a un error legible
        logger.warning("Falló la prueba de conexión SMTP: %r", exc)
        raise ErrorCorreo(_explicar(exc)) from exc
    cifrado = {SMTP_SSL: "SSL/TLS", SMTP_STARTTLS: "STARTTLS"}.get(s.smtp_security, "sin cifrado")
    acceso = f"autenticado como {s.smtp_user}" if s.smtp_user else "sin autenticación"
    return f"Conexión correcta con {s.smtp_host}:{s.smtp_port} ({cifrado}, {acceso})."


def enviar_prueba(destinatario: str = "") -> list[str]:
    """Envía un correo de prueba con la configuración SMTP vigente (guardada).

    A diferencia de ``enviar_alerta`` (mejor esfuerzo, silenciosa), esta función
    valida la configuración y **lanza ``ErrorCorreo``** con un mensaje claro si
    falta algo o el envío falla. Devuelve los destinatarios a los que se envió.
    """
    settings = get_settings()
    if not settings.smtp_host:
        raise ErrorCorreo("Configure primero el servidor SMTP.")
    if not _remitente(settings):
        raise ErrorCorreo("Indique un remitente (o un usuario SMTP que sirva de remitente).")
    destino = [destinatario.strip()] if destinatario.strip() else _destinatarios(settings)
    if not destino:
        raise ErrorCorreo("Indique un destinatario o configure los destinatarios de las alertas.")
    cuerpo = (
        "Este es un correo de PRUEBA del Gestor de Contraseñas de Servidores.\n\n"
        "Si lo recibe, la configuración del servidor de correo es correcta. "
        "Este mensaje no contiene ningún secreto."
    )
    try:
        _enviar_smtp(settings, destino, "Correo de prueba de configuración", cuerpo)
    except Exception as exc:  # noqa: BLE001 — se traduce a un error legible
        logger.warning("Falló el correo de prueba: %r", exc)
        raise ErrorCorreo(_explicar(exc)) from exc
    return destino
