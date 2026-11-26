"""Criterios de aceptación de la v1.4.0: agente Linux, protocolo y panel.

docs/plan-rotacion-agentes.md §8.2, «Aceptación (tests)». Cada criterio se
prueba en algún sitio; esta tabla dice dónde, para que nadie tenga que
reconstruirla. Lo que no estaba probado de punta a punta vive en este archivo.

Contrato del agente (Go, ``agente/internal``)
    Tipo de trabajo desconocido, vencido, concurrente, antes del anti-thrash,
    parámetros fuera de patrón ............ contrato_test.go::TestRechazosDelContrato
    Segundo trabajo con otro en curso ...... contrato_test.go::TestElMismoTrabajoEnCursoNoEsConcurrente,
                                             ejecutor_test.go::TestSinRedElResultadoEsperaEnElJournalYNoSeAceptaOtroTrabajo
    Cuenta inexistente: nunca se crea ...... integracion_test.go::TestIntegracionRechazosDelHelper (root, PAM real)

Contrato del backend
    Trabajo para la credencial de otro activo  test_despacho_agentes.py::test_el_agente_de_otro_activo_no_recibe_el_trabajo,
                                             test_servicio_agentes.py::test_una_credencial_no_puede_rotar_por_el_agente_de_otro_activo
    Agente revocado: sin trabajos .......... test_despacho_agentes.py::test_un_agente_revocado_no_recibe_trabajos
    Doble uso del token de enrolamiento .... test_api_agente.py::test_el_token_de_enrolamiento_no_sirve_dos_veces
    Anti-replay (un resultado por trabajo) . test_despacho_agentes.py::test_un_segundo_resultado_se_rechaza,
                                             test_api_agente.py::test_ciclo_completo_del_agente
    Cuerpo que excede el límite ............ test_api_agente.py::test_toda_ruta_del_agente_tiene_tope_de_cuerpo,
                                             test_la_telemetria_tiene_su_propio_tope
    Token caducado → 401 y estado 🔴 ....... AQUÍ: test_un_token_caducado_da_401_y_la_insignia_lo_dice

Renovación de identidad
    Renovada en el saludo, solapamiento .... test_servicio_agentes.py::test_la_renovacion_deja_valer_el_token_anterior_solo_durante_el_solapamiento,
                                             test_quien_entra_con_el_token_anterior_recibe_otro_nuevo
    La caducidad obliga a re-enrolar ....... AQUÍ: test_la_caducidad_obliga_a_reenrolar
    Dos IPs distintas → anomalía ........... test_servicio_agentes.py::test_renovar_desde_otra_ip_en_la_misma_ventana_es_una_anomalia

Integración (cuenta Linux real)
    Rota, verifica, revierte, sobrevive a un reinicio
        ................................... integracion_test.go (job «agente» de la CI, como root) y
                                             scripts/prueba_agente_sistema.py (job «agente-sistema»:
                                             instalado con systemd en el runner)
    Purga los secretos al cerrar ........... test_despacho_agentes.py::test_aplicado_escribe_la_contrasena_archiva_la_anterior_y_purga,
                                             journal_test.go::TestGuardaCifradoYPurga, y AQUÍ:
                                             test_tras_un_ciclo_completo_ninguna_contrasena_queda_en_claro

Gobernanza heredada de la v1.3.0
    Despacho imposible sin AUTORIZADA ...... test_despacho_agentes.py::test_no_hay_despacho_sin_autorizacion, y
                                             AQUÍ por HTTP: test_sin_autorizacion_la_ruta_de_despacho_no_despacha
    Lo manual se comporta como en la 1.3.0 . AQUÍ: test_lo_manual_no_cambia_aunque_el_activo_tenga_agente
    /api/v1 sin cambio de contrato ......... AQUÍ: test_la_api_v1_no_cambia

Panel
    Enrolamiento y revocación .............. test_api_web_agentes.py, e2e/agentes.spec.ts
    Insignias sin estados fantasma ......... AQUÍ: test_la_insignia_es_siempre_uno_de_los_cinco_estados,
                                             test_un_pendiente_con_el_token_caducado_se_ve_como_tal
    Respaldo: agentes sí, trabajos nunca ... test_despacho_agentes.py::test_el_respaldo_repone_agentes_revocados_y_nunca_trabajos
    Métricas y alerta de agente sin contacto test_api_web_agentes.py::test_las_metricas_cuentan_el_parque_y_senalan_a_los_callados,
                                             test_servicio_agentes.py::test_un_agente_callado_se_avisa_una_vez_por_silencio
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import secrets
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    autorizar_rotacion,
    cabecera_csrf,
    cambiar_password,
    enrolar_mfa_con_codigos,
    login_password,
    sesion_bd,
    solicitar_rotacion,
)
from tests.rutas import rutas_de

ACTUAL = "Actual-Aceptacion-2026!"


@pytest.fixture()
def http(request, monkeypatch):
    """Administrador inicial con los agentes ACTIVADOS y códigos para reautenticarse."""
    monkeypatch.setenv("PASSWD_AGENTES_ENABLED", "true")
    cliente = request.getfixturevalue("client")
    assert login_password(cliente, ADMIN_USER, ADMIN_PASS_INICIAL).status_code == 303
    cambiar_password(cliente, ADMIN_PASS_INICIAL, ADMIN_PASS)
    _secreto, codigos = enrolar_mfa_con_codigos(cliente)
    cliente.codigos = list(codigos)
    return cliente


def _escenario(nombre="srv-aceptacion", *, enrolar=True, client: TestClient | None = None) -> dict:
    """Servidor con una credencial rotada hace un mes y su agente (enrolado si se pide)."""
    from app.models import ACTIVO_FISICO, ServidorFisico, Usuario, ahora_utc
    from app.servicios import agentes, rotacion

    db = sesion_bd()
    admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
    servidor = ServidorFisico(nombre=nombre)
    db.add(servidor)
    db.flush()
    credencial = rotacion.nueva_credencial(db, password=ACTUAL, usuario_acceso="deploy",
                                           servidor_fisico_id=servidor.id)
    db.flush()
    credencial.password_rotada_en = ahora_utc() - timedelta(days=30)
    agente, enrolamiento = agentes.alta(db, tipo_activo=ACTIVO_FISICO, activo_id=servidor.id,
                                        nombre=f"agente-{nombre}", usuario=admin)
    db.commit()
    datos = {"servidor": servidor.id, "credencial": credencial.id, "agente": agente.id,
             "enrolamiento": enrolamiento}
    db.close()
    if enrolar:
        assert client is not None
        datos["privada"], datos["token"] = _enrolar(client, enrolamiento)
    return datos


def _enrolar(client: TestClient, enrolamiento: str):
    privada = X25519PrivateKey.generate()
    publica = base64.b64encode(privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    r = client.post("/api/agent/enrolar", json={"token_enrolamiento": enrolamiento,
                                                "clave_publica": publica, "version": "1.4.0"})
    assert r.status_code == 200, r.text
    return privada, r.json()["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _trabajos() -> int:
    from app.models import TrabajoRotacion

    db = sesion_bd()
    try:
        return db.scalar(select(func.count(TrabajoRotacion.id))) or 0
    finally:
        db.close()


def _cobertura_en_el_panel(client: TestClient, servidor_id: int) -> str:
    r = client.get(f"/api/web/agentes/activo/fisico/{servidor_id}")
    assert r.status_code == 200, r.text
    return r.json()["cobertura"]


def _caducar(agente_id: int) -> None:
    from app.models import Agente, ahora_utc

    db = sesion_bd()
    db.get(Agente, agente_id).token_expira_en = ahora_utc() - timedelta(seconds=1)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Identidad del agente
# ---------------------------------------------------------------------------


def test_un_token_caducado_da_401_y_la_insignia_lo_dice(http):
    """El agente ve 401; quien mira la ficha ve 🔴, no un «conectado» que ya no es verdad."""
    from app import audit
    from app.models import RegistroAuditoria

    esc = _escenario(client=http)
    assert _cobertura_en_el_panel(http, esc["servidor"]) == "conectado"
    _caducar(esc["agente"])

    r = http.post("/api/agent/saludo", headers=_bearer(esc["token"]), json={})
    assert r.status_code == 401
    assert _cobertura_en_el_panel(http, esc["servidor"]) == "caducado"
    db = sesion_bd()
    rechazos = db.scalars(select(RegistroAuditoria).where(
        RegistroAuditoria.accion == audit.AGENTE_ACCESO_RECHAZADO)).all()
    assert any(r.detalle.startswith("401 ") for r in rechazos)
    db.close()


def test_la_caducidad_obliga_a_reenrolar(http):
    """Con la identidad vencida nada la resucita: ni el saludo ni la renovación ni otro latido.

    Solo un token de instalación nuevo, emitido con reautenticación, devuelve el
    agente al servicio; y el token viejo sigue sin valer después.
    """
    esc = _escenario(client=http)
    _caducar(esc["agente"])
    for ruta, metodo in (("/api/agent/saludo", "post"), ("/api/agent/trabajos/pendiente", "get")):
        r = getattr(http, metodo)(ruta, headers=_bearer(esc["token"]),
                                  **({"json": {}} if metodo == "post" else {}))
        assert r.status_code == 401, ruta

    reemision = http.post(f"/api/web/agentes/{esc['agente']}/enrolamiento", headers=cabecera_csrf(http),
                          json={"password": ADMIN_PASS, "codigo": http.codigos.pop()})
    assert reemision.status_code == 200, reemision.text
    _privada, token_nuevo = _enrolar(http, reemision.json()["token_enrolamiento"])

    assert http.post("/api/agent/saludo", headers=_bearer(token_nuevo), json={}).status_code == 200
    assert http.post("/api/agent/saludo", headers=_bearer(esc["token"]), json={}).status_code == 401
    assert _cobertura_en_el_panel(http, esc["servidor"]) == "conectado"


# ---------------------------------------------------------------------------
# Insignias
# ---------------------------------------------------------------------------


def test_la_insignia_es_siempre_uno_de_los_cinco_estados(aplicacion):
    """Barrido de todo lo que decide la insignia: ninguna combinación cae fuera de los cinco
    estados ni contradice lo que el agente puede hacer de verdad."""
    from app.models import AGENTE_ACTIVO, AGENTE_PENDIENTE, AGENTE_REVOCADO, Agente, ahora_utc
    from app.servicios import agentes

    ahora = ahora_utc()
    tokens = {"sin token": None, "vigente": ahora + timedelta(hours=2),
              "caducado": ahora - timedelta(seconds=1)}
    contactos = {"nunca": None, "reciente": ahora - timedelta(minutes=5),
                 "viejo": ahora - timedelta(hours=25)}
    vistos = set()
    for estado, (nombre_token, token), (nombre_contacto, contacto) in itertools.product(
            (AGENTE_PENDIENTE, AGENTE_ACTIVO, AGENTE_REVOCADO), tokens.items(), contactos.items()):
        agente = Agente(servidor_fisico_id=1, nombre="a", estado=estado,
                        token_expira_en=token, ultimo_contacto_en=contacto)
        cobertura = agentes.cobertura(agente, ahora)
        caso = (estado, nombre_token, nombre_contacto)
        vistos.add(cobertura)
        if estado == AGENTE_REVOCADO:
            assert cobertura == agentes.COBERTURA_SIN_AGENTE, caso
        elif estado == AGENTE_PENDIENTE:
            assert cobertura == agentes.COBERTURA_PENDIENTE, caso
        elif nombre_token != "vigente":
            # Sin identidad válida no hay latido posible, por reciente que fuera el último.
            assert cobertura == agentes.COBERTURA_CADUCADO, caso
        elif nombre_contacto != "reciente":
            assert cobertura == agentes.COBERTURA_SIN_CONTACTO, caso
        else:
            assert cobertura == agentes.COBERTURA_CONECTADO, caso
    assert agentes.cobertura(None, ahora) == agentes.COBERTURA_SIN_AGENTE
    assert vistos | {agentes.COBERTURA_SIN_AGENTE} == {
        agentes.COBERTURA_SIN_AGENTE, agentes.COBERTURA_PENDIENTE, agentes.COBERTURA_CONECTADO,
        agentes.COBERTURA_SIN_CONTACTO, agentes.COBERTURA_CADUCADO}


def test_un_pendiente_con_el_token_caducado_se_ve_como_tal(http):
    """Sigue «pendiente», pero la API dice que su token ya no sirve y el enrolamiento lo confirma."""
    from app.models import Agente, ahora_utc

    esc = _escenario(enrolar=False)
    db = sesion_bd()
    db.get(Agente, esc["agente"]).enrolamiento_expira_en = ahora_utc() - timedelta(minutes=1)
    db.commit()
    db.close()

    ficha = http.get(f"/api/web/agentes/activo/fisico/{esc['servidor']}").json()
    assert ficha["cobertura"] == "pendiente"
    assert ficha["agente"]["enrolamiento_expira_en"] < ahora_utc().isoformat()
    r = http.post("/api/agent/enrolar", json={"token_enrolamiento": esc["enrolamiento"],
                                              "clave_publica": base64.b64encode(b"\x01" * 32).decode()})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Gobernanza heredada de la v1.3.0
# ---------------------------------------------------------------------------


def test_sin_autorizacion_la_ruta_de_despacho_no_despacha(http):
    """Pedir el envío al agente de una solicitud que nadie ha autorizado no crea ningún trabajo."""
    esc = _escenario(client=http)
    r = http.post(f"/api/web/agentes/credenciales/{esc['credencial']}/via", headers=cabecera_csrf(http),
                  json={"via": "agente"})
    assert r.json()["via_rotacion"] == "agente"
    solicitud = solicitar_rotacion(http, esc["credencial"]).json()
    assert solicitud["estado"] == "solicitada"

    r = http.post(f"/api/web/rotacion/solicitudes/{solicitud['id']}/despachar", headers=cabecera_csrf(http))
    assert r.status_code >= 400
    assert _trabajos() == 0
    assert http.get("/api/agent/trabajos/pendiente", headers=_bearer(esc["token"])).status_code == 204


def test_lo_manual_no_cambia_aunque_el_activo_tenga_agente(http):
    """Una credencial manual sigue el flujo de la 1.3.0 con un agente conectado al lado.

    Autorizar la deja «autorizada» (no «despachada»), la contraseña la registra
    una persona, y en ningún momento existe un trabajo para el agente.
    """
    from app.models import Credencial
    from app.security.crypto import descifrar

    esc = _escenario(client=http)
    assert http.get(f"/api/web/rotacion/credenciales/{esc['credencial']}").json()["via_rotacion"] == "manual"

    solicitud = solicitar_rotacion(http, esc["credencial"]).json()
    autorizada = autorizar_rotacion(http, solicitud["id"])
    assert autorizada.status_code == 200, autorizada.text
    assert autorizada.json()["estado"] == "autorizada"
    assert _trabajos() == 0
    assert http.get("/api/agent/trabajos/pendiente", headers=_bearer(esc["token"])).status_code == 204

    r = http.post(f"/api/web/rotacion/solicitudes/{solicitud['id']}/aplicar-manual",
                  json={"password": "Nueva-Manual-2026!"}, headers=cabecera_csrf(http))
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cerrada"
    assert r.json()["agente_nombre"] in (None, "")
    assert _trabajos() == 0
    db = sesion_bd()
    assert descifrar(db.get(Credencial, esc["credencial"]).password_cifrada) == "Nueva-Manual-2026!"
    db.close()


# Contrato de /api/v1 en la 1.3.0, congelado: la serie 1.x no lo cambia (§8.0, regla 2).
API_V1_RUTAS = {("GET", "/api/v1/auditoria"), ("GET", "/api/v1/inventario")}
API_V1_INVENTARIO = {
    "servidores_fisicos": {"id", "nombre", "estado", "sistema_operativo", "ip_gestion", "etiquetas"},
    "hipervisores": {"id", "nombre", "plataforma", "version", "estado", "ip_gestion", "marca_modelo",
                     "ubicacion", "ram", "cpu", "almacenamiento", "numero_serie", "garantia_hasta",
                     "proveedor", "etiquetas"},
    "maquinas_virtuales": {"id", "nombre", "estado", "sistema_operativo", "ip", "ram", "cpu",
                           "almacenamiento", "hipervisor_id"},
    "dispositivos_red": {"id", "nombre", "tipo_dispositivo", "estado", "marca_modelo", "version",
                         "ip_gestion", "ubicacion", "puertos", "numero_serie", "garantia_hasta",
                         "proveedor", "etiquetas"},
}
API_V1_EVENTO = {"id", "fecha", "usuario", "accion", "objeto_tipo", "objeto_id", "detalle",
                 "direccion_ip", "exito"}


def test_la_api_v1_no_cambia(http):
    """Ni rutas nuevas ni claves nuevas en /api/v1, aunque haya agentes en el inventario."""
    from app.models import (
        TOKEN_ALCANCE_TODO,
        DispositivoRed,
        Hipervisor,
        MaquinaVirtual,
        TokenApi,
        Usuario,
    )

    rutas = {(r.metodo, r.camino) for r in rutas_de(http.app, incluir_excluidos=True)
             if r.camino.startswith("/api/v1")}
    assert rutas == API_V1_RUTAS

    _escenario(client=http)
    db = sesion_bd()
    hipervisor = Hipervisor(nombre="hv-v1")
    db.add_all([hipervisor, DispositivoRed(nombre="sw-v1", tipo_dispositivo="switch")])
    db.flush()
    db.add(MaquinaVirtual(nombre="vm-v1", hipervisor_id=hipervisor.id))
    admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
    claro = secrets.token_urlsafe(32)
    db.add(TokenApi(nombre="v1", token_hash=hashlib.sha256(claro.encode("ascii")).hexdigest(),
                    alcance=TOKEN_ALCANCE_TODO, creado_por_id=admin.id))
    db.commit()
    db.close()

    cliente = TestClient(http.app)
    inventario = cliente.get("/api/v1/inventario", headers=_bearer(claro)).json()
    assert set(inventario) == set(API_V1_INVENTARIO)
    for coleccion, claves in API_V1_INVENTARIO.items():
        assert inventario[coleccion], coleccion
        assert set(inventario[coleccion][0]) == claves, coleccion
    auditoria = cliente.get("/api/v1/auditoria", headers=_bearer(claro)).json()
    assert set(auditoria) == {"eventos", "ultimo_id"}
    assert auditoria["eventos"] and set(auditoria["eventos"][0]) == API_V1_EVENTO


# ---------------------------------------------------------------------------
# Secretos
# ---------------------------------------------------------------------------


def test_tras_un_ciclo_completo_ninguna_contrasena_queda_en_claro(http):
    """Rotación completa por agente y volcado entero de la base: ni la contraseña anterior
    ni la nueva aparecen en claro en ninguna tabla, tampoco las que el agente intente
    devolver en campos que el protocolo no tiene."""
    from app.models import Credencial
    from app.security.crypto import descifrar
    from app.servicios import cifrado_agente

    esc = _escenario(client=http)
    http.post(f"/api/web/agentes/credenciales/{esc['credencial']}/via", headers=cabecera_csrf(http),
              json={"via": "agente"})
    solicitud = solicitar_rotacion(http, esc["credencial"]).json()
    assert autorizar_rotacion(http, solicitud["id"]).json()["estado"] == "despachada"

    entrega = http.get("/api/agent/trabajos/pendiente", headers=_bearer(esc["token"]))
    assert entrega.status_code == 200, entrega.text
    trabajo = cifrado_agente.abrir(esc["privada"], entrega.json()["sobre"])
    assert trabajo["actual"] == ACTUAL
    r = http.post(f"/api/agent/trabajos/{trabajo['trabajo_id']}/resultado", headers=_bearer(esc["token"]),
                  json={"estado": "aplicado", "verificacion": "local", "detalle": "ok",
                        "nueva": trabajo["nueva"], "password": trabajo["actual"]})
    assert r.status_code == 200, r.text

    db = sesion_bd()
    assert descifrar(db.get(Credencial, esc["credencial"]).password_cifrada) == trabajo["nueva"]
    volcado = "\n".join(db.connection().connection.driver_connection.iterdump())
    db.close()
    # Cordura: el volcado es la base entera, no una vacía.
    assert "srv-aceptacion" in volcado and "deploy" in volcado
    assert ACTUAL not in volcado
    assert trabajo["nueva"] not in volcado
