"""Pruebas de la API REST de solo lectura y la gestión de tokens."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
)
from tests.test_credenciales import _crear_credencial
from tests.test_inventario import _crear_servidor


def _crear_token(admin_client, nombre="siem") -> str:
    csrf = csrf_de(admin_client, "/tokens")
    r = admin_client.post("/tokens", data={"nombre": nombre, "csrf_token": csrf})
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q["nuevo_token"][0]


def test_token_creado_se_muestra_una_vez_y_da_acceso(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-api", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)
    token = _crear_token(client)
    assert len(token) >= 32

    # Acceso a la API con Bearer
    r = client.get("/api/v1/auditoria", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    datos = r.json()
    assert "eventos" in datos and "ultimo_id" in datos
    assert any(e["accion"] == "activo_creado" for e in datos["eventos"])


def test_api_inventario_no_expone_secretos(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-api2", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)  # password = CLAVE_SECRETA
    token = _crear_token(client, "inv")

    r = client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    cuerpo = r.text
    from tests.test_credenciales import CLAVE_SECRETA

    assert CLAVE_SECRETA not in cuerpo            # nunca expone contraseñas
    assert "password" not in cuerpo.lower()
    assert "srv-api2" in cuerpo


def test_api_sin_token_o_invalido_401(client):
    autenticar_admin(client)
    assert client.get("/api/v1/inventario").status_code == 401
    assert client.get("/api/v1/inventario",
                      headers={"Authorization": "Bearer noexiste"}).status_code == 401
    assert client.get("/api/v1/inventario",
                      headers={"Authorization": "Basic xyz"}).status_code == 401


def test_token_revocado_deja_de_funcionar(client):
    autenticar_admin(client)
    token = _crear_token(client, "temporal")
    assert client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # Revocar
    from sqlalchemy import select

    from tests.conftest import sesion_bd

    db = sesion_bd()
    try:
        from app.models import TokenApi

        tid = db.scalar(select(TokenApi.id))
    finally:
        db.close()
    csrf = csrf_de(client, "/tokens")
    assert client.post(f"/tokens/{tid}/revocar", data={"csrf_token": csrf}).status_code == 303
    assert client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_tokens_solo_admin(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "oper-tok", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper-tok", clave)
    assert op.get("/tokens").status_code == 403


def test_api_auditoria_incremental(client):
    autenticar_admin(client)
    token = _crear_token(client)
    r1 = client.get("/api/v1/auditoria?limit=1", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    ultimo = r1.json()["ultimo_id"]
    # Paginación incremental: pedir desde el último id devuelve eventos posteriores
    r2 = client.get(f"/api/v1/auditoria?desde_id={ultimo}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert all(e["id"] > ultimo for e in r2.json()["eventos"])
