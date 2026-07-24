"""Alertas de seguridad por correo (opt-in).

Desactivadas por defecto. Cuando se configuran (PASSWD_NOTIFY_ENABLED=true +
SMTP), envían avisos a los destinatarios definidos ante eventos relevantes
(cuenta bloqueada, posible exfiltración, alta de usuario…). Los mensajes
**nunca** contienen contraseñas ni otros secretos: solo el hecho y su contexto.

El envío es de mejor esfuerzo: un fallo de SMTP se registra pero nunca rompe
el flujo principal de la aplicación.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("passwd.notify")


def _destinatarios(settings) -> list[str]:
    return [d.strip() for d in settings.notify_to.split(",") if d.strip()]


def _enviar_smtp(settings, destinatarios: list[str], asunto: str, cuerpo: str) -> None:
    mensaje = EmailMessage()
    mensaje["Subject"] = f"[{settings.totp_issuer}] {asunto}"
    mensaje["From"] = settings.smtp_from or settings.smtp_user
    mensaje["To"] = ", ".join(destinatarios)
    mensaje.set_content(cuerpo)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as servidor:
        if settings.smtp_tls:
            servidor.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            servidor.login(settings.smtp_user, settings.smtp_password)
        servidor.send_message(mensaje)


def enviar_alerta(asunto: str, cuerpo: str) -> bool:
    """Envía una alerta si las notificaciones están configuradas. No lanza."""
    settings = get_settings()
    destinatarios = _destinatarios(settings)
    if not settings.notify_enabled or not settings.smtp_host or not destinatarios:
        return False
    try:
        _enviar_smtp(settings, destinatarios, asunto, cuerpo)
        return True
    except Exception:  # noqa: BLE001 — el aviso es de mejor esfuerzo
        logger.exception("No se pudo enviar la alerta por correo: %s", asunto)
        return False


class ErrorCorreo(Exception):
    """Fallo al enviar un correo de prueba (mensaje apto para mostrar)."""


def enviar_prueba(destinatario: str = "") -> list[str]:
    """Envía un correo de prueba con la configuración SMTP vigente.

    A diferencia de ``enviar_alerta`` (mejor esfuerzo, silenciosa), esta función
    valida la configuración y **lanza ``ErrorCorreo``** con un mensaje claro si
    falta algo o el envío falla, para que la interfaz de configuración informe al
    administrador si el correo quedó bien configurado. Devuelve la lista de
    destinatarios a los que se envió.
    """
    settings = get_settings()
    if not settings.smtp_host:
        raise ErrorCorreo("Configure primero el servidor SMTP.")
    destino = [destinatario.strip()] if destinatario.strip() else _destinatarios(settings)
    if not destino:
        raise ErrorCorreo("Indique un destinatario o configure la lista de destinatarios.")
    cuerpo = (
        "Este es un correo de PRUEBA del Gestor de Contraseñas de Servidores.\n\n"
        "Si lo recibe, la configuración SMTP de notificaciones es correcta. "
        "Este mensaje no contiene ningún secreto."
    )
    try:
        _enviar_smtp(settings, destino, "Correo de prueba de configuración", cuerpo)
    except Exception as exc:  # noqa: BLE001 — se traduce a un error legible
        logger.warning("Falló el correo de prueba: %s", exc)
        raise ErrorCorreo(f"No se pudo enviar el correo: {exc}") from exc
    return destino
