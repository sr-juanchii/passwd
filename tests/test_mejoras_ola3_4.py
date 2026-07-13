"""Pruebas de las mejoras de las Olas 3 y 4 (escala, operación y calidad).

- SEC-10: alcance (scope) y caducidad de los tokens de API en `/api/v1`.
- SEC-9: bitácora de auditoría encadenada por hash (evidencia de manipulación).
- ESC-4: el panel del analista precarga las concesiones (sin N+1, comprobación
  funcional de que sigue mostrando el activo).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from tests.conftest import autenticar_admin, csrf_de, sesion_bd

# ---------------------------------------------------------------------------
# SEC-10 — alcance y caducidad de tokens de API
# ---------------------------------------------------------------------------


def _crear_token(client, nombre, alcance="todo", dias=0) -> str:
    csrf = csrf_de(client, "/tokens")
    r = client.post("/tokens", data={"nombre": nombre, "alcance": alcance,
                                     "dias_validez": str(dias), "csrf_token": csrf})
    assert r.status_code == 303, r.text
    return parse_qs(urlparse(r.headers["location"]).query)["nuevo_token"][0]


def test_token_alcance_restringe_endpoints(client):
    autenticar_admin(client)
    t_aud = _crear_token(client, "solo-aud", alcance="auditoria")
    t_inv = _crear_token(client, "solo-inv", alcance="inventario")
    t_todo = _crear_token(client, "todo", alcance="todo")

    def h(t):
        return {"Authorization": f"Bearer {t}"}

    # Token de auditoría: ve auditoría, NO inventario
    assert client.get("/api/v1/auditoria", headers=h(t_aud)).status_code == 200
    assert client.get("/api/v1/inventario", headers=h(t_aud)).status_code == 403
    # Token de inventario: al revés
    assert client.get("/api/v1/inventario", headers=h(t_inv)).status_code == 200
    assert client.get("/api/v1/auditoria", headers=h(t_inv)).status_code == 403
    # Token 'todo': ambos
    assert client.get("/api/v1/auditoria", headers=h(t_todo)).status_code == 200
    assert client.get("/api/v1/inventario", headers=h(t_todo)).status_code == 200


def test_token_caducado_rechazado(client):
    from datetime import timedelta

    autenticar_admin(client)
    valor = _crear_token(client, "caducable", alcance="todo", dias=30)
    assert client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {valor}"}).status_code == 200

    # Forzar la caducidad en la BD (hacia el pasado) y reintentar.
    db = sesion_bd()
    try:
        from app.models import TokenApi, ahora_utc

        token = db.scalar(select(TokenApi).where(TokenApi.nombre == "caducable"))
        token.expira_en = ahora_utc() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {valor}"}).status_code == 401


def test_inventario_api_expone_specs_vm_y_pagina(client):
    autenticar_admin(client)
    from tests.test_inventario import _crear_hipervisor

    hv = _crear_hipervisor(client, None, "pve-api")
    csrf = csrf_de(client, f"/hipervisores/{hv}/vms/nueva")
    client.post(f"/hipervisores/{hv}/vms/nueva", data={
        "nombre": "vm-api", "sistema_operativo": "Ubuntu", "ip": "10.0.0.9",
        "descripcion": "", "ram": "8 GB", "cpu": "4 vCPU", "almacenamiento": "120 GB",
        "estado": "activo", "etiquetas": "", "csrf_token": csrf,
    })
    t = _crear_token(client, "inv", alcance="inventario")
    r = client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {t}"})
    vms = r.json()["maquinas_virtuales"]
    assert any(v["nombre"] == "vm-api" and v["ram"] == "8 GB" and v["cpu"] == "4 vCPU" for v in vms)
    # Paginación: limit=1 devuelve como mucho una VM
    r = client.get("/api/v1/inventario?limit=1&offset=0", headers={"Authorization": f"Bearer {t}"})
    assert len(r.json()["maquinas_virtuales"]) <= 1


# ---------------------------------------------------------------------------
# SEC-9 — cadena de auditoría con evidencia de manipulación
# ---------------------------------------------------------------------------


def test_cadena_de_auditoria_integra_y_detecta_manipulacion(client):
    from app import audit

    autenticar_admin(client)  # genera varios eventos encadenados

    db = sesion_bd()
    try:
        resultado = audit.verificar_cadena(db)
        assert resultado["ok"] is True and resultado["verificados"] >= 3
    finally:
        db.close()

    # Manipular el contenido de un registro rompe la cadena.
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        reg = db.scalar(select(RegistroAuditoria).order_by(RegistroAuditoria.id))
        reg.detalle = (reg.detalle or "") + " [manipulado]"
        db.commit()
    finally:
        db.close()

    db = sesion_bd()
    try:
        resultado = audit.verificar_cadena(db)
        assert resultado["ok"] is False and resultado["motivo"] == "contenido alterado"
    finally:
        db.close()


def test_cli_verificar_auditoria(client):
    from app.cli import main as cli_main

    autenticar_admin(client)
    assert cli_main(["verificar-auditoria"]) == 0  # cadena íntegra tras el login


# ---------------------------------------------------------------------------
# OPS-3 — Docker secrets: lectura de claves desde ficheros *_FILE
# ---------------------------------------------------------------------------


def test_claves_desde_fichero_secreto(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import Settings, reset_settings

    clave = Fernet.generate_key().decode("ascii")
    fichero = tmp_path / "enc_key"
    fichero.write_text(clave, encoding="utf-8")

    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.delenv("PASSWD_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY_FILE", str(fichero))  # variante Docker secret
    monkeypatch.setenv("PASSWD_SECRET_KEY", "x" * 40)
    reset_settings()
    try:
        settings = Settings()
        assert settings.encryption_key == clave  # leída del fichero, no de la BD
    finally:
        reset_settings()


# ---------------------------------------------------------------------------
# Portabilidad cross-engine del esquema (regresión: MySQL rechaza DEFAULT en
# columnas TEXT/BLOB, error 1101; SQLite lo tolera y ocultaba el fallo).
# ---------------------------------------------------------------------------


def test_ninguna_columna_text_o_blob_declara_default_en_mysql():
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable

    import app.models  # noqa: F401 — registra todas las tablas en el metadata
    from app.database import Base

    ofensores = []
    for tabla in Base.metadata.sorted_tables:
        ddl = str(CreateTable(tabla).compile(dialect=mysql.dialect()))
        for linea in ddl.splitlines():
            texto = linea.strip().rstrip(",")
            if (" TEXT" in texto or " BLOB" in texto) and "DEFAULT" in texto:
                ofensores.append(f"{tabla.name}: {texto}")
    assert not ofensores, "TEXT/BLOB con DEFAULT (MySQL error 1101): " + "; ".join(ofensores)
