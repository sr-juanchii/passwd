"""Infraestructura de pruebas: aplicación aislada por test y ayudantes de flujo."""

from __future__ import annotations

import datetime
import re

import pyotp
import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin"
ADMIN_EMAIL = "admin@ejemplo.local"
ADMIN_PASS_INICIAL = "Arranque-Seguro-2026!"
ADMIN_PASS = "Definitiva-Segura-2026!"
PASS_USUARIO = "Clave-De-Usuario-2026!"

RE_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
RE_SECRETO = re.compile(r'<code class="codigo-secreto">([^<]+)</code>')
RE_CODIGO_RECUPERACION = re.compile(r'<code class="codigo-recuperacion">([^<]+)</code>')


@pytest.fixture()
def aplicacion(tmp_path, monkeypatch):
    """Aplicación nueva con BD SQLite y claves propias en un directorio temporal."""
    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWD_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("PASSWD_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("PASSWD_ADMIN_PASSWORD", ADMIN_PASS_INICIAL)
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)

    from app.config import reset_settings
    from app.database import reset_engine
    from app.security import ratelimit

    reset_settings()
    reset_engine()
    ratelimit.reiniciar()

    from app.main import create_app

    app = create_app()
    yield app

    reset_engine()
    reset_settings()


@pytest.fixture()
def client(aplicacion) -> TestClient:
    return TestClient(aplicacion, follow_redirects=False)


@pytest.fixture()
def crear_cliente(aplicacion):
    """Fábrica de clientes independientes (cada uno con su propia cookiera)."""

    def _crear() -> TestClient:
        return TestClient(aplicacion, follow_redirects=False)

    return _crear


def extraer_csrf(html: str) -> str:
    coincidencia = RE_CSRF.search(html)
    assert coincidencia, "No se encontró token CSRF en la página"
    return coincidencia.group(1)


def extraer_secreto(html: str) -> str:
    coincidencia = RE_SECRETO.search(html)
    assert coincidencia, "No se encontró el secreto en la página"
    return coincidencia.group(1).strip()


def codigo_totp(secreto: str, desplazamiento_segundos: int = 0) -> str:
    momento = datetime.datetime.now() + datetime.timedelta(seconds=desplazamiento_segundos)
    return pyotp.TOTP(secreto).at(momento)


def login_password(client: TestClient, username: str, password: str):
    """Primer factor: envía usuario y contraseña con el CSRF del formulario."""
    pagina = client.get("/login")
    csrf = extraer_csrf(pagina.text)
    return client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})


def cambiar_password(client: TestClient, actual: str, nueva: str):
    pagina = client.get("/password/cambiar")
    csrf = extraer_csrf(pagina.text)
    return client.post("/password/cambiar", data={
        "password_actual": actual, "password_nueva": nueva,
        "password_confirmacion": nueva, "csrf_token": csrf,
    })


def enrolar_mfa_con_codigos(client: TestClient) -> tuple[str, list[str]]:
    """Completa el enrolamiento TOTP; devuelve (secreto, códigos de recuperación)."""
    pagina = client.get("/mfa/configurar")
    assert pagina.status_code == 200
    secreto = extraer_secreto(pagina.text)
    csrf = extraer_csrf(pagina.text)
    respuesta = client.post("/mfa/configurar", data={"codigo": codigo_totp(secreto), "csrf_token": csrf})
    assert respuesta.status_code == 200, f"Enrolamiento MFA falló: {respuesta.status_code}"
    codigos = RE_CODIGO_RECUPERACION.findall(respuesta.text)
    assert codigos, "No se mostraron códigos de recuperación tras el enrolamiento"
    return secreto, codigos


def enrolar_mfa(client: TestClient) -> str:
    """Completa el enrolamiento TOTP y devuelve el secreto para usos futuros."""
    secreto, _codigos = enrolar_mfa_con_codigos(client)
    return secreto


def verificar_mfa(client: TestClient, secreto: str, desplazamiento: int = 30):
    pagina = client.get("/mfa/verificar")
    csrf = extraer_csrf(pagina.text)
    return client.post("/mfa/verificar", data={
        "codigo": codigo_totp(secreto, desplazamiento), "csrf_token": csrf,
    })


def autenticar_admin(client: TestClient) -> str:
    """Flujo completo del administrador inicial; devuelve su secreto TOTP."""
    r = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert r.status_code == 303 and r.headers["location"] == "/password/cambiar"
    r = cambiar_password(client, ADMIN_PASS_INICIAL, ADMIN_PASS)
    assert r.status_code == 303 and r.headers["location"] == "/mfa/configurar"
    return enrolar_mfa(client)


def csrf_de(client: TestClient, ruta: str) -> str:
    pagina = client.get(ruta)
    assert pagina.status_code == 200, f"GET {ruta} → {pagina.status_code}"
    return extraer_csrf(pagina.text)


def crear_usuario(admin_client: TestClient, username: str, rol: str) -> str:
    """Crea un usuario desde la consola de administración; devuelve la clave temporal."""
    csrf = csrf_de(admin_client, "/usuarios/nuevo")
    respuesta = admin_client.post("/usuarios/nuevo", data={
        "username": username, "email": f"{username}@ejemplo.local",
        "nombre_completo": username.title(), "rol": rol, "csrf_token": csrf,
    })
    assert respuesta.status_code == 200, f"Alta de usuario falló: {respuesta.status_code}"
    return extraer_secreto(respuesta.text)


def autenticar_usuario_nuevo(client: TestClient, username: str, password_temporal: str) -> str:
    """Primer acceso de un usuario creado por el admin; devuelve su secreto TOTP."""
    r = login_password(client, username, password_temporal)
    assert r.status_code == 303 and r.headers["location"] == "/password/cambiar"
    r = cambiar_password(client, password_temporal, PASS_USUARIO)
    assert r.status_code == 303 and r.headers["location"] == "/mfa/configurar"
    return enrolar_mfa(client)


def sesion_bd():
    """Sesión directa a la BD del test para verificaciones de bajo nivel."""
    from app.database import get_db

    return next(get_db())


# ---------------------------------------------------------------------------
# Gobernanza de rotación (v1.3.0)
# ---------------------------------------------------------------------------
#
# Desde la 1.3.0 la contraseña de una credencial no se cambia editando el
# formulario: hace falta una rotación solicitada con motivo y autorizada por
# OTRO administrador. Estos ayudantes montan ese circuito para las pruebas que
# solo necesitan «que la contraseña cambie», sin repetir el flujo en cada una.

MOTIVO_PRUEBA = "Rotación programada de la prueba automatizada del sistema"


def cabecera_csrf(client: TestClient) -> dict[str, str]:
    """Cabecera anti-CSRF para la API JSON, tomada del token de la sesión."""
    return {"X-CSRF-Token": csrf_de(client, "/")}


def segundo_administrador(admin_client: TestClient, username: str = "admin-par"):
    """Crea y autentica un segundo administrador, y lo memoriza en la aplicación.

    La regla de dos pares exige que autorice alguien distinto del solicitante,
    así que casi toda prueba de rotación necesita esta segunda cuenta. Se guarda
    en el estado de la aplicación para no intentar crearla dos veces dentro del
    mismo test.
    """
    estado = admin_client.app.state
    guardado = getattr(estado, "autorizador_pruebas", None)
    if guardado is not None:
        return guardado

    temporal = crear_usuario(admin_client, username, "admin")
    otro = TestClient(admin_client.app, follow_redirects=False)
    r = login_password(otro, username, temporal)
    assert r.status_code == 303 and r.headers["location"] == "/password/cambiar"
    r = cambiar_password(otro, temporal, PASS_USUARIO)
    assert r.status_code == 303 and r.headers["location"] == "/mfa/configurar"
    _secreto, codigos = enrolar_mfa_con_codigos(otro)
    # Se reautentica con códigos de recuperación y no con TOTP: el TOTP solo
    # admite el paso actual y los adyacentes, de modo que una prueba con varias
    # autorizaciones seguidas se quedaría sin códigos válidos. Los de
    # recuperación son de un solo uso y el servicio los acepta igual (no así el
    # código por correo, que la autorización rechaza a propósito).
    estado.autorizador_pruebas = (otro, list(codigos))
    return estado.autorizador_pruebas


def solicitar_rotacion(client: TestClient, credencial_id: int, *,
                       motivo: str = MOTIVO_PRUEBA, tipo: str = "manual"):
    return client.post("/api/web/rotacion/solicitudes",
                       json={"credencial_id": credencial_id, "motivo": motivo, "tipo": tipo},
                       headers=cabecera_csrf(client))


def autorizar_rotacion(admin_client: TestClient, rotacion_id: int):
    """Autoriza con el segundo administrador y su reautenticación."""
    autorizador, codigos = segundo_administrador(admin_client)
    return autorizador.post(
        f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
        json={"password": PASS_USUARIO, "codigo": codigos.pop()},
        headers=cabecera_csrf(autorizador),
    )


def rotar_credencial(admin_client: TestClient, credencial_id: int, password_nueva: str,
                     *, motivo: str = MOTIVO_PRUEBA) -> dict:
    """Ciclo completo: solicitar → autorizar (otro admin) → registrar la nueva.

    Devuelve el asiento del libro mayor ya cerrado.
    """
    r = solicitar_rotacion(admin_client, credencial_id, motivo=motivo)
    assert r.status_code == 200, f"Solicitud rechazada: {r.status_code} {r.text}"
    rotacion_id = r.json()["id"]

    r = autorizar_rotacion(admin_client, rotacion_id)
    assert r.status_code == 200, f"Autorización rechazada: {r.status_code} {r.text}"

    r = admin_client.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/aplicar-manual",
                          json={"password": password_nueva},
                          headers=cabecera_csrf(admin_client))
    assert r.status_code == 200, f"Registro rechazado: {r.status_code} {r.text}"
    return r.json()
