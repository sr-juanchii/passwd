"""Coherencia de la configuración: dependencias, validación y servidor de correo.

- Cada ajuste declara de qué depende, para que la interfaz lo explique.
- Los textos se validan (host, direcciones, emisor) y las reglas ENTRE ajustes
  se comprueban al guardar.
- El servicio de correo tiene su propio interruptor (``smtp_enabled``); las
  alertas a administradores ya no apagan el resto.
- Modos de cifrado: STARTTLS, SSL/TLS implícito y sin cifrado.
- Prueba de conexión con los valores del formulario, sin guardarlos.
- Compatibilidad con instalaciones anteriores (``notify_enabled`` / ``smtp_tls``).
"""

from __future__ import annotations

import smtplib
import ssl
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import autenticar_admin, sesion_bd


def _cab(client) -> dict:
    return {"X-CSRF-Token": client.get("/api/web/session").json()["csrf_token"]}


def _guardar(client, cambios: dict):
    return client.put("/api/web/configuracion", headers=_cab(client), json={"cambios": cambios})


def _ajustes(client) -> dict[str, dict]:
    datos = client.get("/api/web/configuracion").json()
    return {a["clave"]: {**a, "grupo": g["grupo"]} for g in datos["grupos"] for a in g["ajustes"]}


SMTP_OK = {"smtp_enabled": True, "smtp_host": "smtp.empresa.local",
           "smtp_from": "passwd@empresa.local"}


# ---------------------------------------------------------------------------
# Organización y dependencias
# ---------------------------------------------------------------------------


def test_cada_ajuste_esta_en_el_grupo_de_su_funcion(client):
    autenticar_admin(client)
    a = _ajustes(client)
    assert a["totp_issuer"]["grupo"] == "Verificación en dos pasos"
    assert a["email_otp_enabled"]["grupo"] == "Verificación en dos pasos"
    assert a["email_otp_primary_enabled"]["grupo"] == "Verificación en dos pasos"
    assert a["smtp_enabled"]["grupo"] == "Servidor de correo (SMTP)"
    assert a["notify_enabled"]["grupo"] == "Notificaciones"
    assert a["notify_users_enabled"]["grupo"] == "Notificaciones"
    assert a["rotation_warning_days"]["grupo"] == "Notificaciones"
    # Ajuste técnico retirado de la consola; el cifrado ya no es un booleano.
    assert "activity_throttle_seconds" not in a and "smtp_tls" not in a
    assert a["smtp_security"]["tipo"] == "opcion"
    assert {o["valor"] for o in a["smtp_security"]["opciones"]} == {"starttls", "ssl", "ninguna"}


def test_los_ajustes_declaran_sus_dependencias(client):
    autenticar_admin(client)
    a = _ajustes(client)

    def deps(clave: str) -> list[str]:
        return [d["clave"] for d in a[clave]["depende_de"]]

    assert deps("smtp_host") == ["smtp_enabled"]
    assert deps("smtp_password") == ["smtp_enabled", "smtp_user"]
    assert deps("notify_to") == ["smtp_enabled", "notify_enabled"]
    assert deps("email_otp_enabled") == ["smtp_enabled"]
    assert deps("mfa_totp_required_admin") == ["smtp_enabled", "email_otp_primary_enabled"]
    assert deps("rotation_warning_days") == ["smtp_enabled", "notify_users_enabled"]
    assert deps("smtp_enabled") == [] and deps("session_idle_minutes") == []
    # Toda dependencia apunta a un ajuste que existe y trae su etiqueta.
    for ajuste in a.values():
        for d in ajuste["depende_de"]:
            assert d["clave"] in a and d["etiqueta"]


def test_ajustes_antes_solo_de_entorno_ahora_se_editan(client):
    from app.config import get_settings

    autenticar_admin(client)
    r = _guardar(client, {"email_otp_enabled": False, "email_otp_ttl_minutes": 5,
                          "notify_users_enabled": False, "rotation_warning_days": 30,
                          "email_otp_primary_enabled": False, "mfa_totp_required_admin": False})
    assert r.status_code == 200, r.text
    s = get_settings()
    assert (s.email_otp_enabled, s.email_otp_ttl_minutes, s.notify_users_enabled,
            s.rotation_warning_days, s.email_otp_primary_enabled, s.mfa_totp_required_admin) == (
        False, 5, False, 30, False, False)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cambios, fragmento", [
    ({"smtp_host": "smtp://mal.local"}, "host"),
    ({"smtp_host": "smtp.local:587"}, "host"),
    ({"smtp_from": "no-es-correo"}, "dirección"),
    ({"notify_to": "ok@empresa.local, roto"}, "roto"),
    ({"totp_issuer": ""}, "vacío"),
    ({"totp_issuer": "Con[corchetes]"}, "corchetes"),
    ({"smtp_security": "tls-raro"}, "no admite"),
    ({"smtp_user": "x" * 300}, "255"),
])
def test_los_textos_se_validan(client, cambios, fragmento):
    autenticar_admin(client)
    r = _guardar(client, cambios)
    assert r.status_code == 400 and fragmento in r.json()["detail"], r.text


def test_inactividad_no_puede_superar_la_vida_maxima(client):
    autenticar_admin(client)
    r = _guardar(client, {"session_idle_minutes": 600, "session_max_hours": 8})
    assert r.status_code == 400 and "duración máxima" in r.json()["detail"]
    assert _guardar(client, {"session_idle_minutes": 480, "session_max_hours": 8}).status_code == 200
    # También se detecta al cambiar solo uno de los dos.
    assert _guardar(client, {"session_max_hours": 4}).status_code == 400


def test_activar_el_correo_exige_servidor_y_remitente(client):
    autenticar_admin(client)
    r = _guardar(client, {"smtp_enabled": True})
    assert r.status_code == 400 and "servidor SMTP" in r.json()["detail"]
    r = _guardar(client, {"smtp_enabled": True, "smtp_host": "smtp.empresa.local"})
    assert r.status_code == 400 and "remitente" in r.json()["detail"].lower()
    # Un usuario que no es una dirección no sirve de remitente.
    r = _guardar(client, {"smtp_enabled": True, "smtp_host": "smtp.empresa.local", "smtp_user": "relay"})
    assert r.status_code == 400 and "Remitente" in r.json()["detail"]
    # Un usuario con forma de dirección sí.
    assert _guardar(client, {"smtp_enabled": True, "smtp_host": "smtp.empresa.local",
                             "smtp_user": "passwd@empresa.local"}).status_code == 200


def test_alertas_exigen_destinatarios(client):
    autenticar_admin(client)
    assert _guardar(client, SMTP_OK).status_code == 200
    r = _guardar(client, {"notify_enabled": True})
    assert r.status_code == 400 and "destinatario" in r.json()["detail"]
    assert _guardar(client, {"notify_enabled": True,
                             "notify_to": "seguridad@empresa.local"}).status_code == 200


def test_guardar_un_ajuste_ajeno_no_tropieza_con_el_correo(client):
    """Las reglas entre ajustes solo se comprueban si el lote los toca."""
    from app.config import get_settings

    autenticar_admin(client)
    get_settings().smtp_enabled = True  # estado heredado incompleto (sin servidor)
    assert _guardar(client, {"lockout_minutes": 20}).status_code == 200


def test_secreto_sin_cambios_no_se_reescribe_ni_se_audita(client):
    from app.models import RegistroAuditoria

    autenticar_admin(client)
    assert _guardar(client, {"smtp_password": "Clave-SMTP-1"}).json()["modificadas"] == ["smtp_password"]
    assert _guardar(client, {"smtp_password": "Clave-SMTP-1"}).json()["modificadas"] == []
    db = sesion_bd()
    try:
        cambios = [r for r in db.scalars(select(RegistroAuditoria)).all()
                   if r.accion == "configuracion_cambiada"]
        assert len(cambios) == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Servicio de correo: interruptor propio y estado
# ---------------------------------------------------------------------------


def test_las_alertas_ya_no_apagan_el_resto_del_correo(client):
    from app import notifications
    from app.security import otp_correo

    autenticar_admin(client)
    assert _guardar(client, SMTP_OK).status_code == 200
    # Alertas a administradores apagadas (por defecto), servicio encendido.
    assert notifications.correo_operativo() is True
    assert otp_correo.habilitado() is True
    assert notifications.enviar_alerta("X", "y") is False

    assert _guardar(client, {"smtp_enabled": False}).status_code == 200
    assert notifications.correo_operativo() is False
    assert otp_correo.habilitado() is False


def test_estado_del_correo_explica_cada_funcion(client):
    autenticar_admin(client)
    estado = client.get("/api/web/configuracion").json()["correo"]
    assert estado["operativo"] is False and "apagado" in estado["motivo"]
    assert all(f["activa"] is False for f in estado["funciones"])

    _guardar(client, {**SMTP_OK, "smtp_security": "ninguna", "smtp_port": 465, "smtp_user": "u@e.local"})
    estado = client.get("/api/web/configuracion").json()["correo"]
    assert estado["operativo"] is True and estado["motivo"] == ""
    por_nombre = {f["nombre"]: f for f in estado["funciones"]}
    assert por_nombre["Envío de contraseñas temporales"]["activa"] is True
    assert por_nombre["Código por correo como respaldo"]["activa"] is True
    assert por_nombre["Alertas de seguridad a administradores"]["activa"] is False
    avisos = " ".join(estado["avisos"])
    assert "no está cifrada" in avisos and "465" in avisos and "contraseña guardada" in avisos


# ---------------------------------------------------------------------------
# Modos de cifrado y prueba de conexión
# ---------------------------------------------------------------------------


class _SmtpFalso:
    """Sustituto de smtplib.SMTP / SMTP_SSL que registra lo que se le pide."""

    registro: list = []

    def __init__(self, host, port, timeout=None, context=None):
        type(self).registro.append((type(self).__name__, host, port, context is not None))

    def starttls(self, context=None):
        type(self).registro.append("starttls")

    def login(self, usuario, password):
        type(self).registro.append(("login", usuario, password))

    def noop(self):
        type(self).registro.append("noop")

    def send_message(self, mensaje):
        type(self).registro.append(("send", mensaje["From"], mensaje["To"]))

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SmtpSslFalso(_SmtpFalso):
    pass


@pytest.fixture()
def smtp_falso(monkeypatch):
    _SmtpFalso.registro = []
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _SmtpSslFalso)
    return _SmtpFalso.registro


def _parametros(**extra) -> SimpleNamespace:
    base = {"smtp_host": "smtp.local", "smtp_port": 587, "smtp_security": "starttls",
            "smtp_user": "", "smtp_password": "", "smtp_from": "passwd@empresa.local",
            "totp_issuer": "Passwd"}
    return SimpleNamespace(**{**base, **extra})


def test_modo_starttls(smtp_falso):
    from app import notifications

    notifications._enviar_smtp(_parametros(smtp_user="u", smtp_password="p"), ["a@b.local"], "x", "y")
    assert smtp_falso[0][0] == "_SmtpFalso" and smtp_falso[1] == "starttls"
    assert ("login", "u", "p") in smtp_falso
    assert ("send", "passwd@empresa.local", "a@b.local") in smtp_falso


def test_modo_ssl_implicito_usa_smtp_ssl(smtp_falso):
    from app import notifications

    notifications._enviar_smtp(_parametros(smtp_security="ssl", smtp_port=465), ["a@b.local"], "x", "y")
    assert smtp_falso[0] == ("_SmtpSslFalso", "smtp.local", 465, True)
    assert "starttls" not in smtp_falso


def test_modo_sin_cifrado_no_negocia_tls_ni_autentica_sin_usuario(smtp_falso):
    from app import notifications

    notifications._enviar_smtp(_parametros(smtp_security="ninguna", smtp_port=25), ["a@b.local"], "x", "y")
    assert "starttls" not in smtp_falso
    assert not any(isinstance(e, tuple) and e[0] == "login" for e in smtp_falso)


def test_probar_conexion_usa_los_valores_del_formulario_sin_guardar(client, smtp_falso):
    from app.config import get_settings

    autenticar_admin(client)
    _guardar(client, {"smtp_user": "guardado@e.local", "smtp_password": "Clave-Guardada"})
    r = client.post("/api/web/configuracion/probar-conexion", headers=_cab(client), json={"valores": {
        "smtp_host": "nuevo.empresa.local", "smtp_port": 465, "smtp_security": "ssl",
        "smtp_password": "",  # vacía → usa la guardada
    }})
    assert r.status_code == 200, r.text
    assert "nuevo.empresa.local:465" in r.json()["detalle"] and "SSL/TLS" in r.json()["detalle"]
    assert smtp_falso[0] == ("_SmtpSslFalso", "nuevo.empresa.local", 465, True)
    assert ("login", "guardado@e.local", "Clave-Guardada") in smtp_falso and "noop" in smtp_falso
    assert not any(isinstance(e, tuple) and e[0] == "send" for e in smtp_falso)  # no envía nada
    assert "Clave-Guardada" not in r.text
    # Nada de lo probado quedó guardado.
    assert get_settings().smtp_host == "" and get_settings().smtp_security == "starttls"


def test_probar_conexion_valida_y_exige_servidor(client, smtp_falso):
    autenticar_admin(client)
    r = client.post("/api/web/configuracion/probar-conexion", headers=_cab(client), json={"valores": {}})
    assert r.status_code == 400 and "servidor SMTP" in r.json()["detail"]
    r = client.post("/api/web/configuracion/probar-conexion", headers=_cab(client),
                    json={"valores": {"smtp_host": "smtp://x"}})
    assert r.status_code == 400 and "host" in r.json()["detail"]


@pytest.mark.parametrize("excepcion, fragmento", [
    (smtplib.SMTPAuthenticationError(535, b"5.7.8 secreto-interno-del-servidor"), "usuario o la contraseña"),
    (ssl.SSLError("WRONG_VERSION_NUMBER detalle interno"), "modo de seguridad"),
    (ConnectionRefusedError("detalle interno"), "Revise el puerto"),
    (TimeoutError("detalle interno"), "no respondió"),
])
def test_los_errores_smtp_se_explican_sin_filtrar_detalles(client, monkeypatch, excepcion, fragmento):
    def _falla(*a, **k):
        raise excepcion

    monkeypatch.setattr(smtplib, "SMTP", _falla)
    autenticar_admin(client)
    r = client.post("/api/web/configuracion/probar-conexion", headers=_cab(client),
                    json={"valores": {"smtp_host": "smtp.local"}})
    assert r.status_code == 400 and fragmento in r.json()["detail"]
    assert "interno" not in r.text


def test_solo_el_admin_prueba_la_conexion(client, crear_cliente):
    from tests.conftest import autenticar_usuario_nuevo, crear_usuario

    autenticar_admin(client)
    clave = crear_usuario(client, "opsmtp", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "opsmtp", clave)
    r = op.post("/api/web/configuracion/probar-conexion", headers=_cab(op),
                json={"valores": {"smtp_host": "smtp.local"}})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Compatibilidad con instalaciones anteriores
# ---------------------------------------------------------------------------


def test_variables_de_entorno_antiguas_siguen_valiendo(monkeypatch):
    from app import config

    monkeypatch.delenv("PASSWD_SMTP_ENABLED", raising=False)
    monkeypatch.delenv("PASSWD_SMTP_SECURITY", raising=False)
    monkeypatch.setenv("PASSWD_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("PASSWD_SMTP_TLS", "false")
    assert config.base_overridable("smtp_enabled") is True
    assert config.base_overridable("smtp_security") == "ninguna"
    assert config.env_definida("smtp_enabled") and config.env_definida("smtp_security")
    # Las variables nuevas tienen prioridad.
    monkeypatch.setenv("PASSWD_SMTP_ENABLED", "false")
    monkeypatch.setenv("PASSWD_SMTP_SECURITY", "ssl")
    assert config.base_overridable("smtp_enabled") is False
    assert config.base_overridable("smtp_security") == "ssl"


def test_migracion_de_ajustes_de_correo_guardados(client):
    """Una instalación que ya enviaba correo sigue haciéndolo tras actualizar,
    y la migración no se repite (apagar después el servicio es respetado)."""
    from app import ajustes
    from app.config import get_settings
    from app.models import Configuracion

    autenticar_admin(client)
    db = sesion_bd()
    try:
        # Estado «antiguo»: sin marca, con notify_enabled activo y smtp_tls=false.
        for fila in db.scalars(select(Configuracion)).all():
            db.delete(fila)
        db.add(Configuracion(clave="notify_enabled", valor="true"))
        db.add(Configuracion(clave="smtp_tls", valor="false"))
        db.commit()

        assert ajustes.migrar_ajustes_de_correo(db) is True
        ajustes.aplicar(db)
        s = get_settings()
        assert s.smtp_enabled is True and s.smtp_security == "ninguna"
        claves = {f.clave for f in db.scalars(select(Configuracion)).all()}
        assert "smtp_tls" not in claves and "smtp_enabled" in claves

        # El administrador apaga el servicio: la migración no lo vuelve a encender.
        db.delete(db.scalar(select(Configuracion).where(Configuracion.clave == "smtp_enabled")))
        db.commit()
        assert ajustes.migrar_ajustes_de_correo(db) is False
        ajustes.aplicar(db)
        assert get_settings().smtp_enabled is False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Efecto real de los ajustes fuera de la petición web
# ---------------------------------------------------------------------------


def test_el_mantenimiento_usa_la_retencion_configurada(client):
    import datetime

    from app.main import ejecutar_mantenimiento
    from app.models import RegistroAuditoria

    autenticar_admin(client)
    db = sesion_bd()
    try:
        db.add(RegistroAuditoria(
            fecha=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=200),
            username="antiguo", accion="prueba_retencion", detalle="", direccion_ip="", agente_usuario=""))
        db.commit()
    finally:
        db.close()

    def _quedan() -> int:
        d = sesion_bd()
        try:
            return len([r for r in d.scalars(select(RegistroAuditoria)).all()
                        if r.accion == "prueba_retencion"])
        finally:
            d.close()

    ejecutar_mantenimiento()
    assert _quedan() == 1  # con 365 días de retención se conserva
    assert _guardar(client, {"audit_retention_days": 90}).status_code == 200
    ejecutar_mantenimiento()  # sin reiniciar: usa el valor recién configurado
    assert _quedan() == 0


def test_recifrar_incluye_los_secretos_de_configuracion(client, monkeypatch):
    """Tras rotar la clave y recifrar, la contraseña SMTP sigue siendo legible
    solo con la clave nueva."""
    from cryptography.fernet import Fernet

    from app import cli
    from app.config import get_settings
    from app.models import Configuracion

    autenticar_admin(client)
    assert _guardar(client, {"smtp_password": "Clave-A-Rotar"}).status_code == 200
    settings = get_settings()
    antigua = settings.encryption_key
    nueva = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "encryption_key", f"{nueva},{antigua}")

    assert cli.main(["recifrar"]) == 0
    db = sesion_bd()
    try:
        fila = db.scalar(select(Configuracion).where(Configuracion.clave == "smtp_password"))
        assert Fernet(nueva.encode()).decrypt(fila.valor.encode("ascii")).decode() == "Clave-A-Rotar"
    finally:
        db.close()


def test_el_respaldo_conserva_ajustes_y_metodo_mfa(client):
    from app import backup
    from app.config import get_settings
    from app.models import Configuracion, Usuario

    autenticar_admin(client)
    assert _guardar(client, {"smtp_password": "Clave-En-Respaldo", "lockout_minutes": 33}).status_code == 200
    frase = "frase-de-respaldo-larga-2026"
    db = sesion_bd()
    try:
        admin = db.scalar(select(Usuario))
        admin.mfa_metodo = "correo"
        db.commit()
        datos = backup.exportar(db, frase)
        db.commit()
        assert b"Clave-En-Respaldo" not in datos  # va dentro del contenedor cifrado

        for fila in db.scalars(select(Configuracion)).all():
            db.delete(fila)
        admin.mfa_metodo = "totp"
        db.commit()

        backup.restaurar(db, datos, frase, sobrescribir=True)
        db.commit()
        from app import ajustes

        ajustes.aplicar(db)
        assert get_settings().lockout_minutes == 33
        assert get_settings().smtp_password == "Clave-En-Respaldo"
        assert db.scalar(select(Usuario)).mfa_metodo == "correo"
    finally:
        db.close()
