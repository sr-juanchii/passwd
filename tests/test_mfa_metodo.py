"""Segundo factor con método elegible: aplicación autenticadora o correo.

Cubre la API JSON (lo que usa el frontend):

- Alta eligiendo el correo como método principal, y acceso posterior con él.
- La política: el correo como principal se puede deshabilitar y, por defecto, no
  se admite para administradores.
- Una cuenta enrolada por correo que deja de poder usarlo debe configurar TOTP,
  pero SOLO después de acreditar sus dos factores (sin degradación).
- Endurecimiento: los fallos de alta cuentan para el bloqueo y un TOTP de un
  paso temporal ya usado no se acepta.
- «Mi seguridad»: cambio de método y regeneración de códigos con reautenticación.
"""

from __future__ import annotations

import pyotp
from sqlalchemy import select

from tests.conftest import (
    ADMIN_PASS,
    PASS_USUARIO,
    autenticar_admin,
    codigo_totp,
    crear_usuario,
    sesion_bd,
)
from tests.test_avisos_dinamicos import RE_OTP, correos  # noqa: F401 — fixture reutilizada


def _csrf(c) -> dict:
    return {"X-CSRF-Token": c.get("/api/web/session").json()["csrf_token"]}


def _login(c, username: str, password: str):
    csrf_login = c.get("/api/web/csrf").json()["csrf_login"]
    return c.post("/api/web/login", json={
        "username": username, "password": password, "csrf_login": csrf_login})


def _hasta_enrolamiento(admin, crear_cliente, username: str, rol: str = "operador"):
    """Crea un usuario y lo deja en la etapa de alta del segundo factor (JSON)."""
    temporal = crear_usuario(admin, username, rol)
    c = crear_cliente()
    assert _login(c, username, temporal).json()["stage"] == "cambio_password"
    r = c.post("/api/web/password/cambiar", headers=_csrf(c), json={
        "password_actual": temporal, "password_nueva": PASS_USUARIO,
        "password_confirmacion": PASS_USUARIO})
    assert r.json()["stage"] == "mfa_enrolamiento"
    return c


def _ultimo_codigo(correos) -> str:  # noqa: F811
    cuerpos = [m["cuerpo"] for m in correos if RE_OTP.search(m["cuerpo"])]
    assert cuerpos, "No se envió ningún código por correo"
    return RE_OTP.search(cuerpos[-1]).group(1)


def _enrolar_por_correo(c, correos) -> list[str]:  # noqa: F811
    r = c.post("/api/web/mfa/configurar/correo/enviar", headers=_csrf(c))
    assert r.status_code == 200, r.text
    r = c.post("/api/web/mfa/configurar/correo", headers=_csrf(c),
               json={"codigo": _ultimo_codigo(correos)})
    assert r.status_code == 200, r.text
    return r.json()["codigos_recuperacion"]


def _usuario(username: str):
    from app.models import Usuario

    db = sesion_bd()
    return db, db.scalar(select(Usuario).where(Usuario.username == username))


# ---------------------------------------------------------------------------
# Alta y acceso con el correo como método principal
# ---------------------------------------------------------------------------


def test_alta_por_correo_y_acceso_posterior(client, crear_cliente, correos):  # noqa: F811
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "ana")

    opciones = c.get("/api/web/mfa/configurar/metodos").json()
    assert opciones["metodos"] == ["totp", "correo"]
    assert opciones["correo"]["disponible"] is True
    assert opciones["correo"]["destino"].endswith("@ejemplo.local")
    assert "ana@" not in opciones["correo"]["destino"]  # enmascarado

    codigos = _enrolar_por_correo(c, correos)
    assert len(codigos) == 8
    assert c.get("/api/web/session").json()["authenticated"] is True

    db, usuario = _usuario("ana")
    try:
        assert usuario.mfa_metodo == "correo" and usuario.mfa_habilitado
        assert usuario.totp_secret_cifrado is None
    finally:
        db.close()

    # Nuevo acceso: contraseña + código por correo, sin aplicación autenticadora.
    nuevo = crear_cliente()
    assert _login(nuevo, "ana", PASS_USUARIO).json()["stage"] == "mfa_pendiente"
    metodos = nuevo.get("/api/web/mfa/metodos").json()
    assert metodos["principal"] == "correo" and metodos["totp"] is False and metodos["otp_correo"]
    alertas_antes = len([m for m in correos if "respaldo" in m["asunto"].lower()])
    assert nuevo.post("/api/web/mfa/otp-correo", headers=_csrf(nuevo)).status_code == 200
    r = nuevo.post("/api/web/mfa/verificar", headers=_csrf(nuevo),
                   json={"codigo": _ultimo_codigo(correos)})
    assert r.status_code == 200 and r.json()["stage"] == "activa"
    assert "aviso" not in r.json()
    assert nuevo.get("/api/web/dashboard").status_code == 200
    # Usar su método principal no es un acceso «de respaldo»: no alerta.
    assert len([m for m in correos if "respaldo" in m["asunto"].lower()]) == alertas_antes


def test_codigo_de_correo_es_de_un_solo_uso_en_el_acceso(client, crear_cliente, correos):  # noqa: F811
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "berta")
    _enrolar_por_correo(c, correos)

    uno = crear_cliente()
    _login(uno, "berta", PASS_USUARIO)
    uno.post("/api/web/mfa/otp-correo", headers=_csrf(uno))
    codigo = _ultimo_codigo(correos)
    assert uno.post("/api/web/mfa/verificar", headers=_csrf(uno), json={"codigo": codigo}).status_code == 200

    dos = crear_cliente()
    _login(dos, "berta", PASS_USUARIO)
    assert dos.post("/api/web/mfa/verificar", headers=_csrf(dos), json={"codigo": codigo}).status_code == 401


def test_usuario_de_correo_entra_con_codigo_de_recuperacion_sin_smtp(
    client, crear_cliente, correos, monkeypatch,  # noqa: F811
):
    from app.config import get_settings

    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "carla")
    codigos = _enrolar_por_correo(c, correos)

    monkeypatch.setattr(get_settings(), "smtp_host", "", raising=False)  # correo caído
    nuevo = crear_cliente()
    _login(nuevo, "carla", PASS_USUARIO)
    assert nuevo.get("/api/web/mfa/metodos").json()["otp_correo"] is False
    assert nuevo.post("/api/web/mfa/otp-correo", headers=_csrf(nuevo)).status_code == 409
    r = nuevo.post("/api/web/mfa/verificar", headers=_csrf(nuevo), json={"codigo": codigos[0]})
    assert r.status_code == 200 and r.json()["stage"] == "activa"


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------


def test_sin_correo_operativo_solo_se_ofrece_totp(client, crear_cliente):
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "dario")
    opciones = c.get("/api/web/mfa/configurar/metodos").json()
    assert opciones["metodos"] == ["totp"]
    assert opciones["correo"]["disponible"] is False and opciones["correo"]["motivo"]
    assert c.post("/api/web/mfa/configurar/correo/enviar", headers=_csrf(c)).status_code == 409
    assert c.post("/api/web/mfa/configurar/correo", headers=_csrf(c),
                  json={"codigo": "12345678"}).status_code == 409


def test_correo_como_principal_se_puede_deshabilitar(client, crear_cliente, correos, monkeypatch):  # noqa: F811
    from app.config import get_settings

    autenticar_admin(client)
    monkeypatch.setattr(get_settings(), "email_otp_primary_enabled", False, raising=False)
    c = _hasta_enrolamiento(client, crear_cliente, "elena")
    assert c.get("/api/web/mfa/configurar/metodos").json()["metodos"] == ["totp"]
    assert c.post("/api/web/mfa/configurar/correo/enviar", headers=_csrf(c)).status_code == 409


def test_administrador_debe_usar_totp(client, crear_cliente, correos, monkeypatch):  # noqa: F811
    from app.config import get_settings

    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "felix", rol="admin")
    opciones = c.get("/api/web/mfa/configurar/metodos").json()
    assert opciones["metodos"] == ["totp"]
    assert "administrador" in opciones["correo"]["motivo"].lower()
    assert c.post("/api/web/mfa/configurar/correo/enviar", headers=_csrf(c)).status_code == 409

    # Si el administrador del sistema lo relaja, el correo vuelve a ofrecerse.
    monkeypatch.setattr(get_settings(), "mfa_totp_required_admin", False, raising=False)
    assert c.get("/api/web/mfa/configurar/metodos").json()["metodos"] == ["totp", "correo"]


def test_cuenta_de_correo_que_pasa_a_admin_debe_configurar_totp_tras_verificarse(
    client, crear_cliente, correos,  # noqa: F811
):
    """Sin degradación: primero acredita contraseña + código por correo; solo
    entonces se le exige configurar la aplicación. Nunca entra con la contraseña sola."""
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "gema")
    _enrolar_por_correo(c, correos)

    db, usuario = _usuario("gema")
    try:
        usuario.rol = "admin"
        db.commit()
    finally:
        db.close()

    nuevo = crear_cliente()
    assert _login(nuevo, "gema", PASS_USUARIO).json()["stage"] == "mfa_pendiente"
    # Antes de verificar NO puede acceder al alta de TOTP.
    assert nuevo.get("/api/web/mfa/configurar").status_code == 403
    nuevo.post("/api/web/mfa/otp-correo", headers=_csrf(nuevo))
    r = nuevo.post("/api/web/mfa/verificar", headers=_csrf(nuevo),
                   json={"codigo": _ultimo_codigo(correos)})
    assert r.status_code == 200
    assert r.json()["stage"] == "mfa_enrolamiento" and r.json()["next"] == "/mfa/configurar"
    assert nuevo.get("/api/web/dashboard").status_code == 401  # aún no hay sesión activa

    opciones = nuevo.get("/api/web/mfa/configurar/metodos").json()
    assert opciones["metodos"] == ["totp"] and opciones["obligado_totp"] is True
    secreto = nuevo.get("/api/web/mfa/configurar").json()["secreto"]

    # Si abandona aquí, su MFA sigue activo: el siguiente acceso exige el correo.
    db, usuario = _usuario("gema")
    try:
        assert usuario.mfa_habilitado is True and usuario.mfa_metodo == "correo"
    finally:
        db.close()

    r = nuevo.post("/api/web/mfa/configurar", headers=_csrf(nuevo), json={"codigo": codigo_totp(secreto)})
    assert r.status_code == 200
    db, usuario = _usuario("gema")
    try:
        assert usuario.mfa_metodo == "totp"
    finally:
        db.close()
    assert nuevo.get("/api/web/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# Endurecimiento
# ---------------------------------------------------------------------------


def test_fallos_en_el_alta_cuentan_para_el_bloqueo(client, crear_cliente):
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "hugo")
    c.get("/api/web/mfa/configurar")
    cabeceras = _csrf(c)
    estados = [c.post("/api/web/mfa/configurar", headers=cabeceras, json={"codigo": "000000"}).status_code
               for _ in range(5)]
    assert estados[:4] == [400] * 4 and estados[4] == 423
    assert _login(crear_cliente(), "hugo", PASS_USUARIO).status_code == 423


def test_totp_de_un_paso_anterior_al_usado_se_rechaza(client, crear_cliente):
    """Tras aceptar el código del paso t+1, el del paso t (aún dentro de la
    ventana de tolerancia) ya no vale."""
    secreto = autenticar_admin(client)  # el alta consumió el paso t

    uno = crear_cliente()
    _login(uno, "admin", ADMIN_PASS)
    r = uno.post("/api/web/mfa/verificar", headers=_csrf(uno), json={"codigo": codigo_totp(secreto, 30)})
    assert r.status_code == 200  # paso t+1

    dos = crear_cliente()
    _login(dos, "admin", ADMIN_PASS)
    for desplazamiento in (0, -30, 30):  # pasos t, t-1 y el propio t+1
        r = dos.post("/api/web/mfa/verificar", headers=_csrf(dos),
                     json={"codigo": codigo_totp(secreto, desplazamiento)})
        assert r.status_code == 401, f"Se aceptó un TOTP ya superado (desplazamiento {desplazamiento})"


def test_paso_de_codigo_identifica_el_paso_temporal():
    import datetime

    from app.security import mfa

    secreto = mfa.generar_secreto()
    totp = pyotp.TOTP(secreto)
    actual = totp.timecode(datetime.datetime.now())
    assert mfa.paso_de_codigo(secreto, totp.generate_otp(actual)) == actual
    assert mfa.paso_de_codigo(secreto, totp.generate_otp(actual + 1)) == actual + 1
    assert mfa.paso_de_codigo(secreto, totp.generate_otp(actual + 5)) is None
    assert mfa.paso_de_codigo(secreto, "abc") is None


def test_verificacion_mfa_tiene_limite_de_tasa(client, crear_cliente, monkeypatch):
    from app.config import get_settings

    autenticar_admin(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "max_failed_attempts", 50, raising=False)  # aislar del bloqueo
    monkeypatch.setattr(settings, "login_rate_limit", 3, raising=False)
    c = crear_cliente()
    _login(c, "admin", ADMIN_PASS)
    cabeceras = _csrf(c)
    estados = [c.post("/api/web/mfa/verificar", headers=cabeceras, json={"codigo": "000000"}).status_code
               for _ in range(4)]
    assert estados == [401, 401, 401, 429]


# ---------------------------------------------------------------------------
# «Mi seguridad»
# ---------------------------------------------------------------------------


def test_mi_seguridad_cambia_de_totp_a_correo_con_reautenticacion(client, crear_cliente, correos):  # noqa: F811
    autenticar_admin(client)
    temporal = crear_usuario(client, "ines", "operador")
    c = crear_cliente()
    from tests.conftest import autenticar_usuario_nuevo

    autenticar_usuario_nuevo(c, "ines", temporal)  # alta TOTP por la interfaz clásica
    estado = c.get("/api/web/cuenta/seguridad").json()
    assert estado["metodo"] == "totp" and estado["puede_cambiar_a_correo"] is True
    assert estado["codigos_restantes"] == 8

    assert c.post("/api/web/cuenta/mfa/correo/enviar", headers=_csrf(c)).status_code == 200
    codigo = _ultimo_codigo(correos)
    # Contraseña incorrecta: no cambia nada.
    r = c.post("/api/web/cuenta/mfa/correo/activar", headers=_csrf(c),
               json={"password": "no-es-esta", "codigo": codigo})
    assert r.status_code == 400
    assert c.get("/api/web/cuenta/seguridad").json()["metodo"] == "totp"

    r = c.post("/api/web/cuenta/mfa/correo/activar", headers=_csrf(c),
               json={"password": PASS_USUARIO, "codigo": codigo})
    assert r.status_code == 200 and r.json()["metodo"] == "correo"
    db, usuario = _usuario("ines")
    try:
        assert usuario.totp_secret_cifrado is None
    finally:
        db.close()
    # El titular recibe el aviso del cambio en su propio buzón.
    avisos_cambio = [m for m in correos if "verificación en dos pasos" in m["asunto"].lower()]
    assert avisos_cambio and avisos_cambio[-1]["para"] == ["ines@ejemplo.local"]


def test_mi_seguridad_cambia_de_correo_a_totp(client, crear_cliente, correos):  # noqa: F811
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "julia")
    _enrolar_por_correo(c, correos)

    assert c.post("/api/web/cuenta/mfa/totp/iniciar", headers=_csrf(c),
                  json={"password": "mala"}).status_code == 400
    r = c.post("/api/web/cuenta/mfa/totp/iniciar", headers=_csrf(c), json={"password": PASS_USUARIO})
    assert r.status_code == 200
    secreto = r.json()["secreto"]
    # Hasta confirmar, el método sigue siendo el correo.
    assert c.get("/api/web/cuenta/seguridad").json()["metodo"] == "correo"
    assert c.post("/api/web/cuenta/mfa/totp/activar", headers=_csrf(c),
                  json={"codigo": "000000"}).status_code == 400
    r = c.post("/api/web/cuenta/mfa/totp/activar", headers=_csrf(c), json={"codigo": codigo_totp(secreto)})
    assert r.status_code == 200 and r.json()["metodo"] == "totp"


def test_mi_seguridad_regenera_codigos_de_recuperacion(client, crear_cliente):
    secreto = autenticar_admin(client)
    cabeceras = _csrf(client)
    # Sin segundo factor válido no se regeneran.
    r = client.post("/api/web/cuenta/mfa/codigos", headers=cabeceras,
                    json={"password": ADMIN_PASS, "codigo": "000000"})
    assert r.status_code == 400
    r = client.post("/api/web/cuenta/mfa/codigos", headers=cabeceras,
                    json={"password": ADMIN_PASS, "codigo": codigo_totp(secreto, 30)})
    assert r.status_code == 200
    nuevos = r.json()["codigos_recuperacion"]
    assert len(nuevos) == 8 and r.headers["cache-control"] == "no-store"

    # Los nuevos sirven para entrar.
    otro = crear_cliente()
    _login(otro, "admin", ADMIN_PASS)
    assert otro.post("/api/web/mfa/verificar", headers=_csrf(otro), json={"codigo": nuevos[0]}).status_code == 200


def test_mi_seguridad_exige_sesion_activa(client, crear_cliente):
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "kike")
    assert c.get("/api/web/cuenta/seguridad").status_code == 401
    assert c.post("/api/web/cuenta/mfa/codigos", json={"password": "x", "codigo": "y"}).status_code == 401


def test_reset_de_mfa_por_el_admin_devuelve_la_eleccion_de_metodo(client, crear_cliente, correos):  # noqa: F811
    autenticar_admin(client)
    c = _hasta_enrolamiento(client, crear_cliente, "lola")
    _enrolar_por_correo(c, correos)
    db, usuario = _usuario("lola")
    uid = usuario.id
    db.close()

    assert client.post(f"/api/web/usuarios/{uid}/reset-mfa", headers=_csrf(client)).status_code == 200
    db, usuario = _usuario("lola")
    try:
        assert usuario.mfa_habilitado is False and usuario.mfa_metodo == "totp"
    finally:
        db.close()
    nuevo = crear_cliente()
    assert _login(nuevo, "lola", PASS_USUARIO).json()["stage"] == "mfa_enrolamiento"
