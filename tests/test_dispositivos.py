"""Pruebas de los dispositivos de red (switches, routers, firewalls…).

Cubren el ciclo completo del nuevo activo de nivel superior: CRUD web y JSON,
credenciales cifradas con revelado auditado, control de acceso por objeto para
analistas, búsqueda, export/import round-trip, respaldo y API REST.
"""

from __future__ import annotations

import io

from sqlalchemy import func, select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial


def _crear_dispositivo(client, nombre: str, tipo: str = "switch") -> int:
    csrf = csrf_de(client, "/dispositivos/nuevo")
    respuesta = client.post("/dispositivos/nuevo", data={
        "nombre": nombre, "tipo_dispositivo": tipo,
        "marca_modelo": "Cisco Catalyst 9300", "version": "IOS-XE 17.9",
        "ip_gestion": "10.0.0.2", "ubicacion": "Rack A1",
        "puertos": "48x 1GbE + 4x SFP+", "descripcion": f"Descripción de {nombre}",
        "etiquetas": "red, crítico", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó el dispositivo: {respuesta.status_code}"
    return int(respuesta.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def test_crud_dispositivo_web(client):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "sw-core-01")

    detalle = client.get(f"/dispositivos/{dispositivo}")
    assert detalle.status_code == 200
    assert "sw-core-01" in detalle.text
    assert "Switch" in detalle.text
    assert "48x 1GbE + 4x SFP+" in detalle.text

    # Editar: cambia el tipo y el firmware
    csrf = csrf_de(client, f"/dispositivos/{dispositivo}/editar")
    r = client.post(f"/dispositivos/{dispositivo}/editar", data={
        "nombre": "fw-borde-01", "tipo_dispositivo": "firewall",
        "version": "FortiOS 7.4", "ip_gestion": "10.0.0.3", "csrf_token": csrf,
    })
    assert r.status_code == 303
    detalle = client.get(f"/dispositivos/{dispositivo}")
    assert "fw-borde-01" in detalle.text and "Firewall" in detalle.text

    # Nombre duplicado rechazado
    otro = _crear_dispositivo(client, "sw-acceso-01")
    csrf = csrf_de(client, f"/dispositivos/{otro}/editar")
    r = client.post(f"/dispositivos/{otro}/editar", data={
        "nombre": "fw-borde-01", "tipo_dispositivo": "switch", "csrf_token": csrf,
    })
    assert r.status_code == 400

    # Eliminar con credencial: cascada
    _crear_credencial(client, "dispositivo", dispositivo, "admin")
    csrf = csrf_de(client, f"/dispositivos/{dispositivo}")
    r = client.post(f"/dispositivos/{dispositivo}/eliminar", data={"csrf_token": csrf})
    assert r.status_code == 303
    assert client.get(f"/dispositivos/{dispositivo}").status_code == 404

    db = sesion_bd()
    try:
        from app.models import Credencial

        assert (db.scalar(select(func.count(Credencial.id))) or 0) == 0  # cascada
    finally:
        db.close()


def test_credencial_de_dispositivo_cifrada_y_revelable(client):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "rt-wan-01", tipo="router")
    _crear_credencial(client, "dispositivo", dispositivo, "admin")

    db = sesion_bd()
    try:
        from app.models import Credencial
        from app.security.crypto import descifrar

        credencial = db.scalar(select(Credencial))
        assert credencial.tipo_activo == "dispositivo"
        assert credencial.nombre_activo == "rt-wan-01"
        assert CLAVE_SECRETA.encode() not in credencial.password_cifrada
        assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA
        credencial_id = credencial.id
    finally:
        db.close()

    csrf = csrf_de(client, f"/dispositivos/{dispositivo}")
    r = client.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf})
    assert r.status_code == 200
    assert r.json()["password"] == CLAVE_SECRETA
    assert r.headers["cache-control"] == "no-store"

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        acciones = {r.accion for r in db.scalars(select(RegistroAuditoria)).all()}
        assert "credencial_revelada" in acciones
    finally:
        db.close()


def test_tipo_dispositivo_invalido_se_normaliza(client):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "x-desconocido", tipo="impresora")
    db = sesion_bd()
    try:
        from app.models import DispositivoRed

        assert db.get(DispositivoRed, dispositivo).tipo_dispositivo == "switch"
    finally:
        db.close()


def test_analista_y_dispositivos_control_por_objeto(client, crear_cliente):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "sw-restringido")
    _crear_credencial(client, "dispositivo", dispositivo, "admin")

    clave = crear_usuario(client, "analista-red", "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, "analista-red", clave)

    db = sesion_bd()
    try:
        from app.models import Credencial, Usuario

        uid = db.scalar(select(Usuario.id).where(Usuario.username == "analista-red"))
        credencial_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    # Sin concesión: 404 (no filtra existencia)
    assert cli.get(f"/dispositivos/{dispositivo}").status_code == 404

    # Nivel «ver»: ve el activo pero no revela
    csrf = csrf_de(client, "/")
    r = client.post("/accesos/conceder", data={
        "tipo": "dispositivo", "activo_id": str(dispositivo), "usuario_id": str(uid),
        "nivel": "ver", "expira_dias": "", "csrf_token": csrf,
    })
    assert r.status_code == 303
    assert cli.get(f"/dispositivos/{dispositivo}").status_code == 200
    csrf_cli = csrf_de(cli, f"/dispositivos/{dispositivo}")
    assert cli.post(f"/credenciales/{credencial_id}/revelar",
                    data={"csrf_token": csrf_cli}).status_code == 403

    # Nivel «ver_credenciales»: revela
    csrf = csrf_de(client, "/")
    r = client.post("/accesos/conceder", data={
        "tipo": "dispositivo", "activo_id": str(dispositivo), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    assert r.status_code == 303
    r = cli.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf_cli})
    assert r.status_code == 200
    assert r.json()["password"] == CLAVE_SECRETA

    # El panel del analista lista el dispositivo concedido
    panel = cli.get("/")
    assert "sw-restringido" in panel.text
    assert "Dispositivo de red" in panel.text


def test_dashboard_y_busqueda_incluyen_dispositivos(client):
    autenticar_admin(client)
    _crear_dispositivo(client, "sw-buscable")

    panel = client.get("/")
    assert "Dispositivos de red" in panel.text
    assert "sw-buscable" in panel.text

    r = client.get("/buscar", params={"q": "sw-buscable"})
    assert r.status_code == 200
    assert "sw-buscable" in r.text
    assert "Dispositivos de red" in r.text


def test_api_web_crud_dashboard_y_busqueda(client):
    autenticar_admin(client)
    csrf = client.get("/api/web/session").json()["csrf_token"]

    r = client.post("/api/web/dispositivos", headers={"X-CSRF-Token": csrf}, json={
        "nombre": "sw-json-01", "tipo_dispositivo": "balanceador",
        "marca_modelo": "F5 BIG-IP", "version": "17.1", "ip_gestion": "10.0.0.9",
        "ubicacion": "Rack B2", "puertos": "8x 10GbE", "descripcion": "Balanceador",
        "etiquetas": "red",
    })
    assert r.status_code == 200
    did = r.json()["id"]

    # Duplicado → 409
    assert client.post("/api/web/dispositivos", headers={"X-CSRF-Token": csrf},
                       json={"nombre": "SW-JSON-01"}).status_code == 409

    datos = client.get(f"/api/web/dispositivos/{did}").json()
    assert datos["tipo_dispositivo"] == "balanceador"
    assert datos["tipo_dispositivo_label"] == "Balanceador"
    assert datos["puertos"] == "8x 10GbE"
    assert datos["puede_gestionar"] is True

    r = client.put(f"/api/web/dispositivos/{did}", headers={"X-CSRF-Token": csrf}, json={
        "nombre": "sw-json-01", "tipo_dispositivo": "access_point", "version": "2.0",
    })
    assert r.status_code == 200
    assert client.get(f"/api/web/dispositivos/{did}").json()["tipo_dispositivo"] == "access_point"

    tablero = client.get("/api/web/dashboard").json()
    assert tablero["resumen"]["dispositivos"] == 1
    assert tablero["dispositivos"][0]["nombre"] == "sw-json-01"

    busqueda = client.get("/api/web/buscar", params={"q": "sw-json"}).json()
    assert [d["nombre"] for d in busqueda["dispositivos"]] == ["sw-json-01"]

    assert client.delete(f"/api/web/dispositivos/{did}",
                         headers={"X-CSRF-Token": csrf}).json() == {"ok": True}
    assert client.get(f"/api/web/dispositivos/{did}").status_code == 404


def test_export_import_round_trip_con_dispositivos(client):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "sw-migrable")
    _crear_credencial(client, "dispositivo", dispositivo, "admin")

    csrf = csrf_de(client, "/importar")
    exportado = client.post("/exportar", data={"csrf_token": csrf})
    assert exportado.status_code == 200
    texto = exportado.text
    assert "sw-migrable" in texto and CLAVE_SECRETA in texto

    # Vaciar el inventario y re-importar el CSV exportado
    db = sesion_bd()
    try:
        from app.models import Credencial, DispositivoRed

        for fila in db.scalars(select(Credencial)).all():
            db.delete(fila)
        for fila in db.scalars(select(DispositivoRed)).all():
            db.delete(fila)
        db.commit()
    finally:
        db.close()

    csrf = csrf_de(client, "/importar")
    r = client.post("/importar", data={"csrf_token": csrf},
                    files={"archivo": ("inventario.csv", io.BytesIO(texto.encode()), "text/csv")})
    assert r.status_code == 200

    db = sesion_bd()
    try:
        from app.models import Credencial, DispositivoRed
        from app.security.crypto import descifrar

        restaurado = db.scalar(select(DispositivoRed))
        assert restaurado is not None and restaurado.nombre == "sw-migrable"
        assert restaurado.tipo_dispositivo == "switch"
        assert restaurado.puertos == "48x 1GbE + 4x SFP+"
        credencial = db.scalar(select(Credencial).where(
            Credencial.dispositivo_red_id == restaurado.id))
        assert credencial is not None
        assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA
    finally:
        db.close()


def test_plantilla_csv_incluye_dispositivo(client):
    autenticar_admin(client)
    r = client.get("/plantilla.csv")
    assert r.status_code == 200
    assert "tipo_dispositivo" in r.text
    assert "dispositivo" in r.text


def test_respaldo_y_restauracion_con_dispositivos(client):
    autenticar_admin(client)
    dispositivo = _crear_dispositivo(client, "sw-respaldo")
    _crear_credencial(client, "dispositivo", dispositivo, "admin")

    from app import backup

    frase = "frase-de-respaldo-larga-2026"
    db = sesion_bd()
    try:
        datos = backup.exportar(db, frase)
        db.commit()
        resumen = backup.restaurar(db, datos, frase, sobrescribir=True)
        db.commit()
        assert resumen["dispositivos_red"] == 1
        assert resumen["credenciales"] == 1

        from app.models import Credencial, DispositivoRed
        from app.security.crypto import descifrar

        restaurado = db.scalar(select(DispositivoRed))
        assert restaurado.nombre == "sw-respaldo"
        credencial = db.scalar(select(Credencial))
        assert credencial.dispositivo_red_id == restaurado.id
        assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA
    finally:
        db.close()


def test_api_v1_inventario_incluye_dispositivos(client):
    autenticar_admin(client)
    _crear_dispositivo(client, "sw-siem")

    from urllib.parse import parse_qs, urlparse

    csrf = csrf_de(client, "/tokens")
    r = client.post("/tokens", data={"nombre": "siem", "csrf_token": csrf})
    token = parse_qs(urlparse(r.headers["location"]).query)["nuevo_token"][0]

    r = client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    dispositivos = r.json()["dispositivos_red"]
    assert [d["nombre"] for d in dispositivos] == ["sw-siem"]
    assert dispositivos[0]["tipo_dispositivo"] == "switch"
    assert "password" not in r.text.lower()
