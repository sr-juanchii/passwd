"""Alertas de seguridad por correo (opt-in).

Desactivadas por defecto. Cuando se configuran (PASSWD_NOTIFY_ENABLED=true +
SMTP), envían avisos ante eventos relevantes. Hay dos familias de destinatario:

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


def correo_operativo() -> bool:
    """¿Está el correo en condiciones de enviar avisos dinámicos?

    Los avisos por usuario no dependen de ``PASSWD_NOTIFY_TO`` (cada mensaje va
    al buzón de su destinatario), así que solo exigen el interruptor general y un
    servidor SMTP configurado.
    """
    settings = get_settings()
    return bool(settings.notify_enabled and settings.smtp_host)


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
