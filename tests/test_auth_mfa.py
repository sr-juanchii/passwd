"""Pruebas del flujo de autenticación: contraseña, cambio forzado, MFA y sesiones."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    autenticar_admin,
    cambiar_password,
    csrf_de,
    extraer_csrf,
    login_password,
    sesion_bd,
    verificar_mfa,
)


def test_pagina_login_disponible(client):
    respuesta = client.get("/login")
    assert respuesta.status_code == 200
    assert "Iniciar sesión" in respuesta.text


def test_healthz_publico(client):
    respuesta = client.get("/healthz")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_raiz_sin_sesion_redirige_a_login(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"


def test_login_sin_csrf_rechazado(client):
    respuesta = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS_INICIAL})
    assert respuesta.status_code == 403


def test_login_credenciales_invalidas_mensaje_generico(client):
    respuesta = login_password(client, ADMIN_USER, "clave-incorrecta")
    assert respuesta.status_code == 401
    assert "Credenciales inválidas" in respuesta.text

    respuesta = login_password(client, "usuario_fantasma", "lo-que-sea")
    assert respuesta.status_code == 401
    assert "Credenciales inválidas" in respuesta.text  # sin revelar si el usuario existe


def test_flujo_completo_password_cambio_y_mfa(client):
    secreto = autenticar_admin(client)
    assert secreto

    pagina = client.get("/")
    assert pagina.status_code == 200
    assert "Inventario" in pagina.text

    db = sesion_bd()
    try:
        from app.models import Usuario

        admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        assert admin is not None
        assert admin.mfa_habilitado is True
        assert admin.debe_cambiar_password is False
        # El secreto TOTP no se guarda en claro
        assert secreto.encode() not in (admin.totp_secret_cifrado or b"")
    finally:
        db.close()


def test_sesion_pendiente_de_mfa_no_accede_al_inventario(client):
    autenticar_admin(client)
    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})

    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/mfa/verificar"

    # Con el MFA pendiente, el inventario sigue vetado
    assert client.get("/").status_code == 303


def test_mfa_codigo_incorrecto_rechazado(client):
    autenticar_admin(client)
    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})

    login_password(client, ADMIN_USER, ADMIN_PASS)
    pagina = client.get("/mfa/verificar")
    csrf = extraer_csrf(pagina.text)
    respuesta = client.post("/mfa/verificar", data={"codigo": "000000", "csrf_token": csrf})
    assert respuesta.status_code == 401
    assert client.get("/").status_code == 303


def test_mfa_codigo_reutilizado_rechazado(client):
    autenticar_admin(client)
    db = sesion_bd()
    try:
        from app.models import Usuario

        admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        ultimo_usado = admin.ultimo_otp_usado
    finally:
        db.close()
    assert ultimo_usado  # el enrolamiento registró el código consumido

    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})
    login_password(client, ADMIN_USER, ADMIN_PASS)
    pagina = client.get("/mfa/verificar")
    csrf = extraer_csrf(pagina.text)
    respuesta = client.post("/mfa/verificar", data={"codigo": ultimo_usado, "csrf_token": csrf})
    assert respuesta.status_code == 401


def test_relogin_con_mfa(client):
    secreto = autenticar_admin(client)
    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})

    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS)
    assert respuesta.headers["location"] == "/mfa/verificar"
    respuesta = verificar_mfa(client, secreto, desplazamiento=30)
    assert respuesta.status_code == 303
    assert client.get("/").status_code == 200


def test_sesion_expira_por_inactividad(client):
    autenticar_admin(client)
    assert client.get("/").status_code == 200

    db = sesion_bd()
    try:
        import datetime

        from app.models import SesionWeb

        sesion = db.scalar(select(SesionWeb).where(SesionWeb.revocada_en.is_(None)))
        sesion.ultima_actividad -= datetime.timedelta(minutes=16)  # supera los 15 min
        db.commit()
    finally:
        db.close()

    assert client.get("/").status_code == 303  # CIS 4.3: bloqueo por inactividad


def test_sesion_expira_por_vida_maxima(client):
    autenticar_admin(client)

    db = sesion_bd()
    try:
        import datetime

        from app.models import SesionWeb, ahora_utc

        sesion = db.scalar(select(SesionWeb).where(SesionWeb.revocada_en.is_(None)))
        sesion.expira_en = ahora_utc() - datetime.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    assert client.get("/").status_code == 303  # expiración absoluta (8 h)


def test_logout_revoca_la_sesion(client):
    autenticar_admin(client)
    csrf = csrf_de(client, "/")
    respuesta = client.post("/logout", data={"csrf_token": csrf})
    assert respuesta.status_code == 303
    assert client.get("/").status_code == 303


def test_bloqueo_de_cuenta_tras_intentos_fallidos(client):
    for _ in range(5):
        respuesta = login_password(client, ADMIN_USER, "clave-erronea")
        assert respuesta.status_code in (401, 423)

    # Incluso con la contraseña correcta, la cuenta queda bloqueada
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert respuesta.status_code == 423
    assert "bloqueada" in respuesta.text.lower()

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        bloqueos = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "cuenta_bloqueada")).all()
        assert len(bloqueos) == 1
    finally:
        db.close()


def test_limite_de_tasa_por_ip(client):
    for _ in range(15):
        login_password(client, "cualquiera", "x")
    respuesta = login_password(client, "cualquiera", "x")
    assert respuesta.status_code == 429


def test_password_nueva_debe_cumplir_politica(client):
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert respuesta.headers["location"] == "/password/cambiar"

    respuesta = cambiar_password(client, ADMIN_PASS_INICIAL, "corta")
    assert respuesta.status_code == 400
    assert "12 caracteres" in respuesta.text

    respuesta = cambiar_password(client, ADMIN_PASS_INICIAL, "admin-2026-admin-clave")
    assert respuesta.status_code == 400  # contiene el nombre de usuario


def test_cookie_de_sesion_endurecida(client):
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    set_cookie = respuesta.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()


def test_cabeceras_de_seguridad(client):
    respuesta = client.get("/login")
    assert "default-src 'self'" in respuesta.headers["content-security-policy"]
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert respuesta.headers["referrer-policy"] == "no-referrer"
    assert respuesta.headers["cache-control"] == "no-store"


def test_documentacion_api_deshabilitada(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
