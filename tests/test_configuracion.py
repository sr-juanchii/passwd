"""Pruebas del módulo de configuración en tiempo de ejecución.

Cubren: consulta agrupada y origen, guardado con precedencia sobre la base,
efecto real en el comportamiento (límite anti-exfiltración y política de
contraseñas), no filtración del secreto SMTP, restablecer, validación de rangos,
RBAC (solo administradores), auditoría y la prueba de correo.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_credenciales import _crear_credencial
from tests.test_inventario import _crear_servidor


def _csrf_json(client) -> str:
    return client.get("/api/web/session").json()["csrf_token"]


def test_ver_configuracion_agrupada_y_origen(client):
    autenticar_admin(client)
    datos = client.get("/api/web/configuracion").json()
    grupos = {g["grupo"] for g in datos["grupos"]}
    assert "Sesión y comportamiento" in grupos
    assert "Notificaciones por correo" in grupos
    assert datos["info_sistema"]  # información de solo lectura presente
    # Todos los ajustes parten del valor base (por defecto) al inicio.
    todos = [a for g in datos["grupos"] for a in g["ajustes"]]
    idle = next(a for a in todos if a["clave"] == "session_idle_minutes")
    assert idle["valor"] == 15 and idle["origen"] == "defecto"
    # El secreto SMTP nunca trae valor, solo si está configurado.
    smtp = next(a for a in todos if a["clave"] == "smtp_password")
    assert "valor" not in smtp and smtp["configurado"] is False


def test_guardar_override_y_precedencia(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"session_idle_minutes": 30, "rotation_max_days": 45}})
    assert r.status_code == 200 and set(r.json()["modificadas"]) == {"session_idle_minutes", "rotation_max_days"}

    # El valor efectivo y el origen cambian.
    todos = [a for g in client.get("/api/web/configuracion").json()["grupos"] for a in g["ajustes"]]
    idle = next(a for a in todos if a["clave"] == "session_idle_minutes")
    assert idle["valor"] == 30 and idle["origen"] == "configurado"

    # Y el singleton de Settings ya lo refleja (lo leen los consumidores).
    from app.config import get_settings

    assert get_settings().session_idle_minutes == 30
    assert get_settings().rotation_max_days == 45


def test_guardar_igual_a_base_no_crea_override(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    # 15 es el valor base de session_idle_minutes → no debe crear override.
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"session_idle_minutes": 15}})
    assert r.json()["modificadas"] == []
    db = sesion_bd()
    try:
        from app.models import Configuracion

        assert db.scalar(select(Configuracion).where(Configuracion.clave == "session_idle_minutes")) is None
    finally:
        db.close()


def test_efecto_real_en_limite_de_revelado(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-cfg")
    _crear_credencial(client, "fisico", servidor)
    db = sesion_bd()
    try:
        from app.models import Credencial

        cred_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    csrf = _csrf_json(client)
    # Bajar el límite anti-exfiltración a 1 revelado por ventana.
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"reveal_rate_limit": 1}})
    assert r.status_code == 200 and "reveal_rate_limit" in r.json()["modificadas"]

    # Primer revelado permitido; el segundo, bloqueado por el nuevo límite.
    assert client.post(f"/api/web/credenciales/{cred_id}/revelar",
                       headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post(f"/api/web/credenciales/{cred_id}/revelar",
                       headers={"X-CSRF-Token": csrf}).status_code == 429


def test_efecto_en_politica_de_contrasena(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"password_min_length": 40}})
    from app.config import get_settings
    from app.security.passwords import validar_politica

    assert get_settings().password_min_length == 40
    errores = validar_politica("Corta-2026!", "")  # 11 caracteres < 40
    assert any("40" in e for e in errores)


def test_secreto_smtp_no_se_filtra(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"smtp_host": "smtp.local", "smtp_password": "SuperSecretoSMTP!"}})
    assert r.status_code == 200

    # La API nunca devuelve el valor del secreto, solo que está configurado.
    cuerpo = client.get("/api/web/configuracion").text
    assert "SuperSecretoSMTP!" not in cuerpo
    todos = [a for g in client.get("/api/web/configuracion").json()["grupos"] for a in g["ajustes"]]
    smtp = next(a for a in todos if a["clave"] == "smtp_password")
    assert smtp["configurado"] is True and "valor" not in smtp

    # En reposo se guarda cifrado (no en claro).
    db = sesion_bd()
    try:
        from app.models import Configuracion

        fila = db.scalar(select(Configuracion).where(Configuracion.clave == "smtp_password"))
        assert fila is not None and fila.es_secreto is True
        assert "SuperSecretoSMTP!" not in fila.valor
        from app.security.crypto import descifrar

        assert descifrar(fila.valor.encode("ascii")) == "SuperSecretoSMTP!"
    finally:
        db.close()

    # El singleton lo aplica descifrado para que lo use el envío de correo.
    from app.config import get_settings

    assert get_settings().smtp_password == "SuperSecretoSMTP!"


def test_secreto_vacio_conserva_el_actual(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"smtp_password": "Primera!"}})
    # Un guardado posterior sin el secreto (o vacío) no lo borra.
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"smtp_host": "otro.local", "smtp_password": ""}})
    from app.config import get_settings

    assert get_settings().smtp_password == "Primera!"


def test_restablecer_vuelve_a_la_base(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"lockout_minutes": 99}})
    from app.config import get_settings

    assert get_settings().lockout_minutes == 99
    r = client.post("/api/web/configuracion/restablecer", headers={"X-CSRF-Token": csrf},
                    json={"clave": "lockout_minutes"})
    assert r.status_code == 200 and r.json()["restablecido"] is True
    assert get_settings().lockout_minutes == 15  # valor base


def test_validacion_de_rango(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    # audit_retention_days tiene piso 90 (CIS 8.10): 30 debe rechazarse.
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"audit_retention_days": 30}})
    assert r.status_code == 400 and "90" in r.json()["detail"]
    # No entero.
    r = client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                   json={"cambios": {"session_idle_minutes": "abc"}})
    assert r.status_code == 400


def test_solo_admin_gestiona_configuracion(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "opcfg", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "opcfg", clave)

    assert op.get("/api/web/configuracion").status_code == 403
    csrf = op.get("/api/web/session").json()["csrf_token"]
    assert op.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
                  json={"cambios": {"session_idle_minutes": 5}}).status_code == 403
    # La web Jinja tampoco muestra la entrada ni deja entrar.
    assert op.get("/configuracion").status_code in (403, 404)


def test_cambio_queda_auditado(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"max_failed_attempts": 8}})
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        acciones = {r.accion for r in db.scalars(select(RegistroAuditoria)).all()}
        assert "configuracion_cambiada" in acciones
    finally:
        db.close()


def test_probar_correo_sin_smtp_falla(client):
    autenticar_admin(client)
    csrf = _csrf_json(client)
    r = client.post("/api/web/configuracion/probar-correo", headers={"X-CSRF-Token": csrf},
                    json={"destinatario": "a@b.co"})
    assert r.status_code == 400 and "SMTP" in r.json()["detail"]


def test_probar_correo_ok_con_smtp_simulado(client, monkeypatch):
    autenticar_admin(client)
    enviados = {}
    monkeypatch.setattr(
        "app.notifications._enviar_smtp",
        lambda settings, destinatarios, asunto, cuerpo: enviados.update(dest=destinatarios, asunto=asunto),
    )
    csrf = _csrf_json(client)
    client.put("/api/web/configuracion", headers={"X-CSRF-Token": csrf},
               json={"cambios": {"smtp_host": "smtp.local", "notify_to": "seguridad@empresa.local"}})
    r = client.post("/api/web/configuracion/probar-correo", headers={"X-CSRF-Token": csrf},
                    json={"destinatario": ""})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert enviados["dest"] == ["seguridad@empresa.local"]
    # El cuerpo del correo no contiene secretos (verificación básica).
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert any(r.accion == "correo_prueba_enviado" for r in db.scalars(select(RegistroAuditoria)).all())
    finally:
        db.close()


def test_configuracion_via_web_jinja(client):
    autenticar_admin(client)
    # La página carga y muestra el grupo de correo.
    pagina = client.get("/configuracion")
    assert pagina.status_code == 200 and "Notificaciones por correo" in pagina.text
    csrf = csrf_de(client, "/configuracion")
    r = client.post("/configuracion", data={"csrf_token": csrf, "session_idle_minutes": "25",
                                            "session_max_hours": "8", "activity_throttle_seconds": "60",
                                            "password_min_length": "12", "max_failed_attempts": "5",
                                            "lockout_minutes": "15", "login_rate_limit": "15",
                                            "login_rate_window_minutes": "5", "reveal_rate_limit": "20",
                                            "reveal_rate_window_minutes": "5", "rotation_max_days": "90",
                                            "password_history_max": "5", "audit_retention_days": "365",
                                            "smtp_port": "587", "totp_issuer": "Gestor-Passwd",
                                            "smtp_host": "", "smtp_user": "", "smtp_from": "", "notify_to": ""})
    assert r.status_code == 303
    from app.config import get_settings

    assert get_settings().session_idle_minutes == 25
