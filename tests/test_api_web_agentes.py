"""Panel de agentes (`/api/web/agentes`) y rutas de ejecución por agente (v1.4.0, 3c).

La frontera del panel: permiso, CSRF, control de acceso por objeto y la
reautenticación que se pide para crear identidades de máquina y para resolver a
mano una rotación sin confirmar.
"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    PASS_USUARIO,
    autenticar_usuario_nuevo,
    autorizar_rotacion,
    cabecera_csrf,
    cambiar_password,
    crear_usuario,
    enrolar_mfa_con_codigos,
    login_password,
    sesion_bd,
    solicitar_rotacion,
)


@pytest.fixture()
def http(request, monkeypatch):
    """Cliente del administrador inicial, con los agentes activados y códigos para reautenticarse."""
    monkeypatch.setenv("PASSWD_AGENTES_ENABLED", "true")
    cliente = request.getfixturevalue("client")
    r = login_password(cliente, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert r.status_code == 303
    cambiar_password(cliente, ADMIN_PASS_INICIAL, ADMIN_PASS)
    _secreto, codigos = enrolar_mfa_con_codigos(cliente)
    cliente.codigos = list(codigos)
    return cliente


def _reauth(cliente) -> dict:
    """Contraseña + un código de recuperación (de un solo uso, como el TOTP de un paso)."""
    return {"password": ADMIN_PASS, "codigo": cliente.codigos.pop()}


def _servidor(nombre="srv-panel", restringido=False) -> tuple[int, int]:
    from app.models import ServidorFisico, ahora_utc
    from app.servicios import rotacion

    db = sesion_bd()
    servidor = ServidorFisico(nombre=nombre, restringido=restringido)
    db.add(servidor)
    db.flush()
    credencial = rotacion.nueva_credencial(db, password="Actual-Panel-2026!", usuario_acceso="deploy",
                                           servidor_fisico_id=servidor.id)
    db.flush()
    credencial.password_rotada_en = ahora_utc() - timedelta(days=30)
    db.commit()
    ids = servidor.id, credencial.id
    db.close()
    return ids


def _alta(http, servidor_id, nombre="agente-panel"):
    return http.post("/api/web/agentes", headers=cabecera_csrf(http), json={
        "tipo_activo": "fisico", "activo_id": servidor_id, "nombre": nombre, **_reauth(http)})


def _enrolar(http, token_enrolamiento):
    privada = X25519PrivateKey.generate()
    publica = base64.b64encode(privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    r = http.post("/api/agent/enrolar", json={"token_enrolamiento": token_enrolamiento,
                                              "clave_publica": publica, "version": "1.4.0"})
    assert r.status_code == 200, r.text
    return privada, r.json()["token"]


def _operador(http) -> TestClient:
    temporal = crear_usuario(http, "operador-agentes", "operador")
    otro = TestClient(http.app, follow_redirects=False)
    autenticar_usuario_nuevo(otro, "operador-agentes", temporal)
    return otro


# ---------------------------------------------------------------------------
# Alta y su reautenticación
# ---------------------------------------------------------------------------


def test_dar_de_alta_un_agente_exige_reautenticacion(http):
    from app import audit
    from app.models import Agente, RegistroAuditoria

    servidor_id, _ = _servidor()
    sin = http.post("/api/web/agentes", headers=cabecera_csrf(http),
                    json={"tipo_activo": "fisico", "activo_id": servidor_id, "nombre": "a"})
    malo = http.post("/api/web/agentes", headers=cabecera_csrf(http),
                     json={"tipo_activo": "fisico", "activo_id": servidor_id, "nombre": "a",
                           "password": ADMIN_PASS, "codigo": "000000"})
    assert sin.status_code >= 400 and malo.status_code >= 400

    db = sesion_bd()
    assert db.scalars(select(Agente)).all() == []
    denegados = db.scalars(select(RegistroAuditoria)
                           .where(RegistroAuditoria.accion == audit.ACCESO_DENEGADO)).all()
    assert len(denegados) == 2               # la evidencia sobrevive al rollback
    db.close()


def test_el_token_de_instalacion_se_ve_una_sola_vez(http):
    servidor_id, _ = _servidor()
    r = _alta(http, servidor_id)
    assert r.status_code == 200, r.text
    token = r.json()["token_enrolamiento"]
    assert token and r.json()["agente"]["cobertura"] == "pendiente"

    listado = http.get("/api/web/agentes")
    assert listado.status_code == 200
    assert token not in listado.text
    assert "hash" not in listado.text


def test_reemitir_el_token_de_instalacion_tambien_exige_reautenticacion(http):
    servidor_id, _ = _servidor()
    agente_id = _alta(http, servidor_id).json()["agente"]["id"]
    r = http.post(f"/api/web/agentes/{agente_id}/enrolamiento", headers=cabecera_csrf(http), json={})
    assert r.status_code >= 400
    r = http.post(f"/api/web/agentes/{agente_id}/enrolamiento", headers=cabecera_csrf(http),
                  json=_reauth(http))
    assert r.status_code == 200 and r.json()["token_enrolamiento"]


def test_con_los_agentes_apagados_no_se_dan_de_alta(client):
    from tests.conftest import autenticar_admin

    autenticar_admin(client)
    assert client.get("/api/web/agentes").json()["habilitados"] is False


# ---------------------------------------------------------------------------
# Permisos y acceso por objeto
# ---------------------------------------------------------------------------


def test_el_operador_ve_los_agentes_pero_no_los_gestiona(http):
    servidor_id, _ = _servidor()
    _alta(http, servidor_id)
    operador = _operador(http)
    assert len(operador.get("/api/web/agentes").json()["agentes"]) == 1
    r = operador.post("/api/web/agentes", headers=cabecera_csrf(operador),
                      json={"tipo_activo": "fisico", "activo_id": servidor_id, "nombre": "x",
                            "password": PASS_USUARIO, "codigo": "000000"})
    assert r.status_code == 403


def test_el_agente_de_un_activo_restringido_no_existe_para_el_operador(http):
    servidor_id, _ = _servidor("srv-restringido", restringido=True)
    agente_id = _alta(http, servidor_id).json()["agente"]["id"]
    operador = _operador(http)
    assert operador.get("/api/web/agentes").json()["agentes"] == []
    assert operador.get(f"/api/web/agentes/activo/fisico/{servidor_id}").status_code == 404
    assert http.get(f"/api/web/agentes/activo/fisico/{servidor_id}").json()["agente"]["id"] == agente_id


# ---------------------------------------------------------------------------
# Vía de rotación, revocación y resolución
# ---------------------------------------------------------------------------


def test_revocar_devuelve_las_credenciales_al_flujo_manual(http):
    servidor_id, credencial_id = _servidor()
    alta = _alta(http, servidor_id).json()
    _enrolar(http, alta["token_enrolamiento"])
    r = http.post(f"/api/web/agentes/credenciales/{credencial_id}/via", headers=cabecera_csrf(http),
                  json={"via": "agente"})
    assert r.json()["via_rotacion"] == "agente"

    r = http.post(f"/api/web/agentes/{alta['agente']['id']}/revocar", headers=cabecera_csrf(http))
    assert r.status_code == 200 and r.json()["agente"]["estado"] == "revocado"
    ficha = http.get(f"/api/web/rotacion/credenciales/{credencial_id}").json()
    assert ficha["via_rotacion"] == "manual"


def test_resolver_un_sin_confirmar_exige_reautenticacion(http):
    from app.models import Credencial, TrabajoRotacion, ahora_utc
    from app.security.crypto import descifrar
    from app.servicios import cifrado_agente
    from app.servicios import rotacion as servicio

    servidor_id, credencial_id = _servidor()
    alta = _alta(http, servidor_id).json()
    privada, token = _enrolar(http, alta["token_enrolamiento"])
    http.post(f"/api/web/agentes/credenciales/{credencial_id}/via", headers=cabecera_csrf(http),
              json={"via": "agente"})
    rotacion_id = solicitar_rotacion(http, credencial_id).json()["id"]
    assert autorizar_rotacion(http, rotacion_id).json()["estado"] == "despachada"

    entrega = http.get("/api/agent/trabajos/pendiente", headers={"Authorization": f"Bearer {token}"})
    contenido = cifrado_agente.abrir(privada, entrega.json()["sobre"])
    trabajo_id = contenido["trabajo_id"]

    # El agente calla: pasada la ventana y el margen, queda «sin confirmar».
    db = sesion_bd()
    db.get(TrabajoRotacion, trabajo_id).ventana_expira_en = (
        ahora_utc() - servicio.MARGEN_CONFIRMACION - timedelta(minutes=1))
    db.commit()
    db.close()
    panel = http.get("/api/web/rotacion/panel").json()
    assert [t["id"] for t in panel["sin_confirmar"]] == [trabajo_id]

    r = http.post(f"/api/web/rotacion/trabajos/{trabajo_id}/resolver", headers=cabecera_csrf(http),
                  json={"aplicada": True})
    assert r.status_code >= 400
    r = http.post(f"/api/web/rotacion/trabajos/{trabajo_id}/resolver", headers=cabecera_csrf(http),
                  json={"aplicada": True, **_reauth(http)})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cerrada"

    db = sesion_bd()
    assert descifrar(db.get(Credencial, credencial_id).password_cifrada) == contenido["nueva"]
    db.close()
