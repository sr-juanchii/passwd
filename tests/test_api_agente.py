"""API de los agentes (`/api/agent`, v1.4.0, commit 3b).

Contrato: docs/plan-rotacion-agentes.md §3.3. El agente se autentica con su
propia identidad (Bearer), sin cookies ni CSRF; las reglas las pone el servicio y
aquí se prueba que la frontera HTTP no las debilita.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.rutas import rutas_de

MOTIVO = "Rotación periódica por agente de la prueba de la API"


@pytest.fixture()
def app_agentes(request, monkeypatch):
    monkeypatch.setenv("PASSWD_AGENTES_ENABLED", "true")
    return request.getfixturevalue("aplicacion")


@pytest.fixture()
def http(app_agentes):
    return TestClient(app_agentes)


def _bd():
    from tests.conftest import sesion_bd

    return sesion_bd()


def _par():
    privada = X25519PrivateKey.generate()
    publica = base64.b64encode(privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return privada, publica


def _alta(nombre="srv-api"):
    """Dos administradores, un servidor, su credencial y el alta del agente (por servicio)."""
    from app.models import ACTIVO_FISICO, ROL_ADMIN, ServidorFisico, Usuario, ahora_utc
    from app.servicios import agentes, rotacion

    db = _bd()
    pide = Usuario(username=f"pide-{nombre}", email=f"pide-{nombre}@ejemplo.local",
                   password_hash="x", rol=ROL_ADMIN)
    autoriza = Usuario(username=f"aut-{nombre}", email=f"aut-{nombre}@ejemplo.local",
                       password_hash="x", rol=ROL_ADMIN)
    servidor = ServidorFisico(nombre=nombre)
    db.add_all([pide, autoriza, servidor])
    db.flush()
    credencial = rotacion.nueva_credencial(db, password="Actual-Api-2026!", usuario_acceso="deploy",
                                           servidor_fisico_id=servidor.id)
    db.flush()
    credencial.password_rotada_en = ahora_utc() - timedelta(days=30)
    agente, enrolamiento = agentes.alta(db, tipo_activo=ACTIVO_FISICO, activo_id=servidor.id,
                                        nombre=f"agente-{nombre}", usuario=pide)
    db.commit()
    ids = {"pide": pide.id, "autoriza": autoriza.id, "credencial": credencial.id, "agente": agente.id}
    db.close()
    return ids, enrolamiento


def _enrolar(http, enrolamiento, ip_host="srv-api"):
    privada, publica = _par()
    r = http.post("/api/agent/enrolar", json={"token_enrolamiento": enrolamiento,
                                              "clave_publica": publica,
                                              "nombre_host": ip_host, "version": "1.4.0"})
    assert r.status_code == 200, r.text
    return privada, r.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _rotacion_autorizada(ids):
    """La credencial pasa a rotar por agente; se solicita y otro admin autoriza."""
    from app.models import Credencial, Usuario
    from app.servicios import agentes, rotacion

    db = _bd()
    credencial = db.get(Credencial, ids["credencial"])
    pide, autoriza = db.get(Usuario, ids["pide"]), db.get(Usuario, ids["autoriza"])
    agentes.usar_agente(db, credencial=credencial, usuario=pide)
    solicitud = rotacion.solicitar(db, credencial=credencial, usuario=pide, motivo=MOTIVO)
    rotacion.autorizar(db, rotacion=solicitud, usuario=autoriza)
    db.commit()
    db.close()


def _acciones(accion):
    from app.models import RegistroAuditoria

    db = _bd()
    try:
        return db.scalars(select(RegistroAuditoria).where(RegistroAuditoria.accion == accion)).all()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Superficie
# ---------------------------------------------------------------------------


def test_toda_ruta_del_agente_exige_su_identidad(app_agentes, http):
    """La garantía que la matriz de permisos no puede dar para este prefijo.

    Se enumera del registro real: una ruta nueva en `/api/agent` que no exija la
    identidad del agente hace fallar esta prueba.
    """
    # Con un agente enrolado en la base: una autenticación que cayera en «el
    # primero que haya» no podría esconderse tras una tabla vacía.
    _ids, enrolamiento = _alta()
    _enrolar(http, enrolamiento)

    rutas = [r for r in rutas_de(app_agentes, incluir_excluidos=True) if r.camino.startswith("/api/agent")]
    assert len(rutas) >= 5
    for ruta in rutas:
        camino = ruta.camino.replace("{trabajo_id}", "1")
        for cabeceras in ({}, _bearer("inventado")):
            respuesta = http.request(ruta.metodo, camino, headers=cabeceras, json={})
            assert respuesta.status_code == 401, f"{ruta.clave} {cabeceras} → {respuesta.status_code}"


def test_con_los_agentes_apagados_el_prefijo_no_existe(client):
    assert client.post("/api/agent/saludo", json={}).status_code == 404
    assert client.post("/api/agent/enrolar", json={}).status_code == 404


# ---------------------------------------------------------------------------
# El ciclo completo por HTTP
# ---------------------------------------------------------------------------


def test_ciclo_completo_del_agente(http):
    from app.models import Credencial
    from app.security.crypto import descifrar
    from app.servicios import cifrado_agente

    ids, enrolamiento = _alta()
    privada, token = _enrolar(http, enrolamiento)

    r = http.post("/api/agent/saludo", headers=_bearer(token), json={"version": "1.4.0"})
    assert r.status_code == 200 and r.json()["version_admitida"] is True
    assert http.get("/api/agent/trabajos/pendiente", headers=_bearer(token)).status_code == 204

    _rotacion_autorizada(ids)
    r = http.get("/api/agent/trabajos/pendiente", headers=_bearer(token))
    assert r.status_code == 200
    contenido = cifrado_agente.abrir(privada, r.json()["sobre"])
    assert contenido["usuario"] == "deploy" and contenido["actual"] == "Actual-Api-2026!"

    r = http.post(f"/api/agent/trabajos/{contenido['trabajo_id']}/resultado",
                  headers=_bearer(token), json={"estado": "aplicado", "verificacion": "local"})
    assert r.status_code == 200, r.text

    db = _bd()
    assert descifrar(db.get(Credencial, ids["credencial"]).password_cifrada) == contenido["nueva"]
    db.close()

    # Anti-replay por HTTP: el mismo resultado otra vez.
    r = http.post(f"/api/agent/trabajos/{contenido['trabajo_id']}/resultado",
                  headers=_bearer(token), json={"estado": "aplicado"})
    assert r.status_code == 409


def test_el_token_de_enrolamiento_no_sirve_dos_veces(http):
    _ids, enrolamiento = _alta()
    _enrolar(http, enrolamiento)
    _, publica = _par()
    r = http.post("/api/agent/enrolar", json={"token_enrolamiento": enrolamiento, "clave_publica": publica})
    assert r.status_code == 401


def test_un_token_caducado_no_entra(http):
    from app.models import Agente, ahora_utc

    ids, enrolamiento = _alta()
    _privada, token = _enrolar(http, enrolamiento)
    db = _bd()
    db.get(Agente, ids["agente"]).token_expira_en = ahora_utc() - timedelta(seconds=1)
    db.commit()
    db.close()
    r = http.post("/api/agent/saludo", headers=_bearer(token), json={})
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_un_agente_no_cierra_el_trabajo_de_otro_y_queda_auditado(http):
    from app import audit

    ids, enrolamiento = _alta("srv-dueno")
    _privada, token = _enrolar(http, enrolamiento)
    _ids_b, enrolamiento_b = _alta("srv-intruso")
    _privada_b, token_b = _enrolar(http, enrolamiento_b)
    _rotacion_autorizada(ids)
    trabajo_id = http.get("/api/agent/trabajos/pendiente", headers=_bearer(token)).json()["trabajo_id"]

    r = http.post(f"/api/agent/trabajos/{trabajo_id}/resultado", headers=_bearer(token_b),
                  json={"estado": "aplicado"})
    assert r.status_code == 403
    # El rechazo sobrevive al rollback de la petición fallida.
    assert _acciones(audit.TRABAJO_RESULTADO_RECHAZADO)
    assert _acciones(audit.AGENTE_ACCESO_RECHAZADO)


def test_sin_identidad_el_rechazo_queda_en_la_bitacora(http):
    from app import audit

    assert http.post("/api/agent/saludo", json={}).status_code == 401
    assert http.post("/api/agent/saludo", headers=_bearer("inventado"), json={}).status_code == 401
    assert len(_acciones(audit.AGENTE_ACCESO_RECHAZADO)) == 2


def test_la_telemetria_tiene_su_propio_tope(http):
    from app.models import TelemetriaAgente

    _ids, enrolamiento = _alta()
    _privada, token = _enrolar(http, enrolamiento)
    ok = http.post("/api/agent/telemetria", headers=_bearer(token),
                   json={"cpu_pct": 12, "ram_pct": 40, "discos": [{"montaje": "/", "usado_pct": 61}]})
    assert ok.status_code == 204

    enorme = {"cpu_pct": 1, "sistema_operativo": "x", "discos": [{"montaje": "/" + "a" * 200}] * 100}
    assert len(json.dumps(enorme)) > 16 * 1024
    assert http.post("/api/agent/telemetria", headers=_bearer(token), json=enorme).status_code == 413

    db = _bd()
    assert len(db.scalars(select(TelemetriaAgente)).all()) == 1
    db.close()


def test_el_limite_de_tasa_del_agente(http, monkeypatch):
    import app.api_agent as api_agente

    monkeypatch.setattr(api_agente, "LIMITE_AGENTE", 3)
    _ids, enrolamiento = _alta()
    _privada, token = _enrolar(http, enrolamiento)
    codigos = [http.post("/api/agent/saludo", headers=_bearer(token), json={}).status_code
               for _ in range(5)]
    assert codigos[:3] == [200, 200, 200] and codigos[3:] == [429, 429]
