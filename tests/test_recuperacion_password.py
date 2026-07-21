"""Auto-recuperación de contraseña: usuario + email → 2.º factor → nueva clave.

Cubre el camino feliz (TOTP y código de recuperación), la anti-enumeración
(identidad incorrecta responde igual pero sin desafío real), el tope de
intentos, la caducidad del desafío, la revocación de sesiones y que un usuario
sin MFA activo no puede auto-recuperarse.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import RecuperacionPassword, SesionWeb, Usuario, ahora_utc
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    cambiar_password,
    codigo_totp,
    enrolar_mfa_con_codigos,
    extraer_csrf,
    login_password,
    sesion_bd,
)

NUEVA = "Recuperada-Firme-2026!#"


def _preparar_admin(client) -> tuple[str, list[str]]:
    """Bootstrap del admin capturando su secreto TOTP y códigos de recuperación."""
    r = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert r.status_code == 303
    r = cambiar_password(client, ADMIN_PASS_INICIAL, ADMIN_PASS)
    assert r.status_code == 303
    return enrolar_mfa_con_codigos(client)


def _iniciar(client, username: str, email: str):
    pagina = client.get("/recuperar")
    assert pagina.status_code == 200
    csrf = extraer_csrf(pagina.text)
    return client.post(
        "/recuperar",
        data={"username": username, "email": email, "csrf_token": csrf},
        follow_redirects=False,
    )


def _verificar(client, codigo: str):
    pagina = client.get("/recuperar/verificar", follow_redirects=False)
    if pagina.status_code != 200:  # sin desafío vigente → redirige a /recuperar
        return pagina
    csrf = extraer_csrf(pagina.text)
    return client.post(
        "/recuperar/verificar",
        data={"codigo": codigo, "csrf_token": csrf},
        follow_redirects=False,
    )


def _cambiar(client, nueva: str):
    pagina = client.get("/recuperar/cambiar", follow_redirects=False)
    assert pagina.status_code == 200, "El paso de cambio exige un desafío verificado"
    csrf = extraer_csrf(pagina.text)
    return client.post(
        "/recuperar/cambiar",
        data={"password_nueva": nueva, "password_confirmacion": nueva, "csrf_token": csrf},
        follow_redirects=False,
    )


def test_recuperacion_camino_feliz_con_totp(client):
    secreto, _codigos = _preparar_admin(client)

    r = _iniciar(client, ADMIN_USER, ADMIN_EMAIL)
    assert r.status_code == 303 and r.headers["location"] == "/recuperar/verificar"

    # Código de una ventana adelante: válido (valid_window=1) y distinto del
    # último OTP usado durante el enrolamiento, evitando el guard de reutilización.
    r = _verificar(client, codigo_totp(secreto, 30))
    assert r.status_code == 303 and r.headers["location"] == "/recuperar/cambiar"

    r = _cambiar(client, NUEVA)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")

    # La nueva contraseña funciona; la antigua ya no.
    assert login_password(client, ADMIN_USER, NUEVA).status_code == 303
    assert login_password(client, ADMIN_USER, ADMIN_PASS).status_code == 401


def test_recuperacion_con_codigo_de_recuperacion(client):
    _secreto, codigos = _preparar_admin(client)

    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303
    # Un código de recuperación (dispositivo perdido) autoriza el cambio.
    r = _verificar(client, codigos[0])
    assert r.status_code == 303 and r.headers["location"] == "/recuperar/cambiar"
    assert _cambiar(client, NUEVA).status_code == 303
    assert login_password(client, ADMIN_USER, NUEVA).status_code == 303

    # El código de recuperación queda consumido (no sirve para un segundo intento).
    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303
    r = _verificar(client, codigos[0])
    assert r.status_code == 401


def test_identidad_incorrecta_no_emite_desafio_pero_responde_igual(client):
    _preparar_admin(client)

    # Email que no corresponde: misma respuesta (303 + cookie) que el caso válido…
    r = _iniciar(client, ADMIN_USER, "otro@ejemplo.local")
    assert r.status_code == 303 and r.headers["location"] == "/recuperar/verificar"
    assert "passwd_recuperacion" in r.headers.get("set-cookie", "")

    # …pero no hay desafío real: el paso de verificación redirige a /recuperar.
    r = _verificar(client, "000000")
    assert r.status_code == 303 and r.headers["location"] == "/recuperar"

    # No se creó ninguna fila de desafío para el usuario.
    db = sesion_bd()
    try:
        assert db.scalar(select(RecuperacionPassword)) is None
    finally:
        db.close()


def test_usuario_sin_mfa_no_puede_recuperar(client):
    # Admin recién arrancado: primer factor OK pero sin MFA enrolado todavía.
    login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    cambiar_password(client, ADMIN_PASS_INICIAL, ADMIN_PASS)
    # NO se enrola MFA. La cuenta existe pero mfa_habilitado sigue en False.

    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303
    r = _verificar(client, "000000")
    assert r.status_code == 303 and r.headers["location"] == "/recuperar"
    db = sesion_bd()
    try:
        assert db.scalar(select(RecuperacionPassword)) is None
    finally:
        db.close()


def test_tope_de_intentos_agota_el_desafio(client):
    _preparar_admin(client)
    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303

    # Cuatro fallos por debajo del tope siguen re-renderizando (401).
    for _ in range(4):
        assert _verificar(client, "000000").status_code == 401
    # El quinto fallo agota el desafío y expulsa a /recuperar.
    r = _verificar(client, "000000")
    assert r.status_code == 303 and r.headers["location"] == "/recuperar"
    # Un código correcto posterior ya no sirve: el desafío está consumido.
    assert _verificar(client, "000000").status_code == 303


def test_desafio_caducado_se_rechaza(client):
    _preparar_admin(client)
    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303

    db = sesion_bd()
    try:
        desafio = db.scalar(select(RecuperacionPassword))
        desafio.expira_en = ahora_utc() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    r = _verificar(client, "000000")
    assert r.status_code == 303 and r.headers["location"] == "/recuperar"


def test_recuperacion_json_camino_feliz_y_anti_enumeracion(client):
    secreto, _codigos = _preparar_admin(client)

    # Identidad incorrecta: misma respuesta (200 {ok} + Set-Cookie) que el caso válido.
    csrf_login = client.get("/api/web/csrf").json()["csrf_login"]
    r_mal = client.post("/api/web/password/recuperar/iniciar",
                        json={"username": ADMIN_USER, "email": "no@existe.local", "csrf_login": csrf_login})
    assert r_mal.status_code == 200 and r_mal.json()["ok"] is True
    assert "passwd_recuperacion" in r_mal.headers.get("set-cookie", "")
    # Sin desafío real, la verificación falla (400) pese a la cookie presente.
    csrf_falso = r_mal.json()["csrf"]
    r_vf = client.post("/api/web/password/recuperar/verificar", json={"codigo": "000000"},
                       headers={"X-CSRF-Token": csrf_falso})
    assert r_vf.status_code == 400

    # Camino feliz por JSON.
    csrf_login = client.get("/api/web/csrf").json()["csrf_login"]
    r = client.post("/api/web/password/recuperar/iniciar",
                    json={"username": ADMIN_USER, "email": ADMIN_EMAIL, "csrf_login": csrf_login})
    assert r.status_code == 200
    csrf_d = r.json()["csrf"]
    r_v = client.post("/api/web/password/recuperar/verificar", json={"codigo": codigo_totp(secreto, 30)},
                      headers={"X-CSRF-Token": csrf_d})
    assert r_v.status_code == 200 and r_v.json()["ok"] is True
    # CSRF ausente en el paso de cambio → 403.
    assert client.post("/api/web/password/recuperar/cambiar",
                       json={"password_nueva": NUEVA, "password_confirmacion": NUEVA}).status_code == 403
    r_c = client.post("/api/web/password/recuperar/cambiar",
                      json={"password_nueva": NUEVA, "password_confirmacion": NUEVA},
                      headers={"X-CSRF-Token": csrf_d})
    assert r_c.status_code == 200 and r_c.json()["next"] == "/login"
    assert login_password(client, ADMIN_USER, NUEVA).status_code == 303


def test_recuperacion_revoca_todas_las_sesiones(client):
    secreto, _codigos = _preparar_admin(client)

    # Sesión activa del admin antes de recuperar.
    db = sesion_bd()
    try:
        admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        vivas_antes = db.scalars(
            select(SesionWeb).where(SesionWeb.usuario_id == admin.id, SesionWeb.revocada_en.is_(None))
        ).all()
        assert len(vivas_antes) >= 1
    finally:
        db.close()

    assert _iniciar(client, ADMIN_USER, ADMIN_EMAIL).status_code == 303
    assert _verificar(client, codigo_totp(secreto, 30)).status_code == 303
    assert _cambiar(client, NUEVA).status_code == 303

    db = sesion_bd()
    try:
        admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        vivas_despues = db.scalars(
            select(SesionWeb).where(SesionWeb.usuario_id == admin.id, SesionWeb.revocada_en.is_(None))
        ).all()
        assert vivas_despues == []
    finally:
        db.close()
