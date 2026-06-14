"""Pruebas del endurecimiento OWASP: copiado sin visualización, límite
anti-exfiltración, tamaño máximo de petición y cabeceras de aislamiento."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_servidor


def _credencial_id():
    db = sesion_bd()
    try:
        from app.models import Credencial

        return db.scalar(select(Credencial.id))
    finally:
        db.close()


def test_copiar_entrega_la_clave_sin_mostrarla_y_queda_auditado(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-copiar", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)
    credencial_id = _credencial_id()

    csrf = csrf_de(client, f"/servidores/{fisico}")
    respuesta = client.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf})
    assert respuesta.status_code == 200
    assert respuesta.json()["password"] == CLAVE_SECRETA
    assert respuesta.headers["cache-control"] == "no-store"

    # La página nunca contiene la contraseña; el copiado se audita aparte del revelado
    detalle = client.get(f"/servidores/{fisico}")
    assert CLAVE_SECRETA not in detalle.text
    assert 'data-copiar="' in detalle.text

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        copiados = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "credencial_copiada")).all()
        assert len(copiados) == 1
        assert copiados[0].username == "admin"
    finally:
        db.close()


def test_auditor_no_puede_copiar(client, crear_cliente):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-copiar-rbac", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)
    credencial_id = _credencial_id()
    clave_temporal = crear_usuario(client, "auditorcopia", "auditor")

    cliente_auditor = crear_cliente()
    autenticar_usuario_nuevo(cliente_auditor, "auditorcopia", clave_temporal)
    csrf = csrf_de(cliente_auditor, f"/servidores/{fisico}")
    respuesta = cliente_auditor.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf})
    assert respuesta.status_code == 403


def test_limite_anti_exfiltracion_de_contrasenas(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-exfiltracion", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)
    credencial_id = _credencial_id()

    from app.config import get_settings
    from app.security import ratelimit

    settings = get_settings()
    original = settings.reveal_rate_limit
    settings.reveal_rate_limit = 3
    ratelimit.reiniciar()
    try:
        csrf = csrf_de(client, f"/servidores/{fisico}")
        # Revelados y copiados comparten el mismo presupuesto por usuario
        assert client.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf}).status_code == 200
        assert client.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf}).status_code == 200
        assert client.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf}).status_code == 200

        bloqueada = client.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf})
        assert bloqueada.status_code == 429
    finally:
        settings.reveal_rate_limit = original
        ratelimit.reiniciar()

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        excesos = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "revelado_tasa_excedido")).all()
        assert len(excesos) == 1  # el intento bloqueado quedó como evidencia
        assert excesos[0].exito is False
    finally:
        db.close()


def test_peticion_demasiado_grande_rechazada(client):
    # OWASP API4: un cuerpo desproporcionado (con Content-Length) se corta antes
    respuesta = client.post(
        "/login",
        data={"username": "x" * 70000, "password": "y", "csrf_token": "z"},
    )
    assert respuesta.status_code == 413


def test_peticion_chunked_demasiado_grande_rechazada(client):
    # OWASP API4: un cuerpo en streaming (Transfer-Encoding: chunked, sin
    # Content-Length) tampoco debe eludir el límite.
    def cuerpo_grande():
        for _ in range(80):
            yield b"x" * 1024  # ~80 KB en trozos, sin declarar tamaño

    respuesta = client.post(
        "/login",
        content=cuerpo_grande(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert respuesta.status_code == 413


def test_respuesta_413_conserva_cabeceras_de_seguridad(client):
    # El 413 se cortocircuita, pero CabecerasSeguridad es la capa más externa:
    # la respuesta debe llevar igualmente las cabeceras de seguridad.
    respuesta = client.post(
        "/login",
        data={"username": "x" * 70000, "password": "y", "csrf_token": "z"},
    )
    assert respuesta.status_code == 413
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in respuesta.headers


def test_cabeceras_de_aislamiento_de_origen(client):
    respuesta = client.get("/login")
    assert respuesta.headers["cross-origin-opener-policy"] == "same-origin"
    assert respuesta.headers["cross-origin-resource-policy"] == "same-origin"
    assert respuesta.headers["x-permitted-cross-domain-policies"] == "none"


def test_js_copia_sin_mostrar_con_limpieza_de_portapapeles(client):
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "escribirPortapapeles" in js.text
    assert "isSecureContext" in js.text          # API segura solo en HTTPS
    assert 'escribirPortapapeles("")' in js.text  # limpieza del portapapeles
