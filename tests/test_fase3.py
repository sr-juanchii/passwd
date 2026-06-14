"""Pruebas de la Fase 3 — notificaciones email, rate limit en BD, retención."""

from __future__ import annotations

from sqlalchemy import func, select

from tests.conftest import login_password, sesion_bd

# ---------------------------------------------------------------------------
# Notificaciones por correo (opt-in, mejor esfuerzo, sin secretos)
# ---------------------------------------------------------------------------


def test_alerta_desactivada_por_defecto_no_envia(aplicacion, monkeypatch):
    from app import notifications

    llamadas = []
    monkeypatch.setattr(notifications, "_enviar_smtp",
                        lambda *a, **k: llamadas.append(a))
    # Sin NOTIFY_ENABLED ni SMTP configurados → no se intenta enviar.
    assert notifications.enviar_alerta("X", "cuerpo") is False
    assert llamadas == []


def test_alerta_se_envia_cuando_esta_configurada(aplicacion, monkeypatch):
    from app import notifications
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "notify_enabled", True)
    monkeypatch.setattr(s, "smtp_host", "smtp.local")
    monkeypatch.setattr(s, "notify_to", "seguridad@org.tld")
    capturado = {}
    monkeypatch.setattr(notifications, "_enviar_smtp",
                        lambda settings, dest, asunto, cuerpo: capturado.update(
                            dest=dest, asunto=asunto, cuerpo=cuerpo))
    assert notifications.enviar_alerta("Cuenta bloqueada", "detalle sin secretos") is True
    assert capturado["dest"] == ["seguridad@org.tld"]
    assert "Cuenta bloqueada" in capturado["asunto"]


def test_alerta_fallo_smtp_no_rompe(aplicacion, monkeypatch):
    from app import notifications
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "notify_enabled", True)
    monkeypatch.setattr(s, "smtp_host", "smtp.local")
    monkeypatch.setattr(s, "notify_to", "x@org.tld")

    def _falla(*a, **k):
        raise OSError("SMTP caído")

    monkeypatch.setattr(notifications, "_enviar_smtp", _falla)
    # No debe propagar la excepción; devuelve False.
    assert notifications.enviar_alerta("X", "y") is False


# ---------------------------------------------------------------------------
# Limitador de tasa con backend en BD
# ---------------------------------------------------------------------------


def test_rate_limit_backend_bd(aplicacion, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    db = sesion_bd()
    try:
        monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")
        # Límite 3 en 5 min: el 4.º intento se rechaza.
        assert ratelimit.permitir_intento("prueba", limite=3, ventana_minutos=5, db=db) is True
        assert ratelimit.permitir_intento("prueba", limite=3, ventana_minutos=5, db=db) is True
        assert ratelimit.permitir_intento("prueba", limite=3, ventana_minutos=5, db=db) is True
        assert ratelimit.permitir_intento("prueba", limite=3, ventana_minutos=5, db=db) is False

        from app.models import EventoTasa

        n = db.scalar(select(func.count(EventoTasa.id)).where(EventoTasa.clave == "prueba"))
        assert n == 3  # solo los permitidos quedan registrados
    finally:
        db.close()


def test_login_rate_limit_funciona_con_backend_bd(aplicacion, crear_cliente, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")
    monkeypatch.setattr(get_settings(), "login_rate_limit", 3)
    ratelimit.reiniciar()
    cli = crear_cliente()
    estados = [login_password(cli, "x", "y").status_code for _ in range(4)]
    assert estados[-1] == 429  # el backend en BD también frena la fuerza bruta


# ---------------------------------------------------------------------------
# Retención de respaldos en la CLI
# ---------------------------------------------------------------------------


def test_retencion_de_respaldos(tmp_path):
    # 5 respaldos; conservar 2 → se eliminan 3.
    import os
    import time

    from app.cli import _podar_respaldos

    for i in range(5):
        f = tmp_path / f"respaldo-{i}.passwd"
        f.write_bytes(b"x")
        os.utime(f, (time.time() + i, time.time() + i))  # mtime creciente
    eliminados = _podar_respaldos(tmp_path / "respaldo-4.passwd", retener=2)
    assert eliminados == 3
    quedan = sorted(p.name for p in tmp_path.glob("*.passwd"))
    assert quedan == ["respaldo-3.passwd", "respaldo-4.passwd"]  # los 2 más recientes
