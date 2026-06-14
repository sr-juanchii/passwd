"""Pruebas de la Fase 2 — inventario más rico (hardware, estado, etiquetas)."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import autenticar_admin, csrf_de, sesion_bd


def _crear_servidor_completo(client, nombre, **extra):
    csrf = csrf_de(client, "/servidores/nuevo")
    datos = {
        "nombre": nombre, "tipo": "funcion_unica", "csrf_token": csrf,
        "ram": "64 GB", "cpu": "2x Xeon", "almacenamiento": "2x 960GB SSD",
        "numero_serie": "SN-123", "garantia_hasta": "2027-03", "proveedor": "ACME",
        "estado": "mantenimiento", "etiquetas": "Producción, Crítico, dmz",
    }
    datos.update(extra)
    r = client.post("/servidores/nuevo", data=datos)
    assert r.status_code == 303, r.status_code
    return int(r.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def test_servidor_con_hardware_estado_y_etiquetas(client):
    autenticar_admin(client)
    sid = _crear_servidor_completo(client, "srv-rico")

    db = sesion_bd()
    try:
        from app.models import ServidorFisico

        s = db.get(ServidorFisico, sid)
        assert s.ram == "64 GB" and s.cpu == "2x Xeon"
        assert s.numero_serie == "SN-123" and s.proveedor == "ACME"
        assert s.estado == "mantenimiento"
        # Etiquetas normalizadas (minúsculas, sin duplicados, separadas por ", ")
        assert s.etiquetas == "producción, crítico, dmz"
        assert s.lista_etiquetas == ["producción", "crítico", "dmz"]
    finally:
        db.close()

    detalle = client.get(f"/servidores/{sid}")
    assert "64 GB" in detalle.text
    assert "En mantenimiento" in detalle.text
    assert "producción" in detalle.text


def test_estado_invalido_cae_en_activo(client):
    autenticar_admin(client)
    sid = _crear_servidor_completo(client, "srv-estado", estado="inexistente")
    db = sesion_bd()
    try:
        from app.models import ServidorFisico

        assert db.get(ServidorFisico, sid).estado == "activo"
    finally:
        db.close()


def test_busqueda_por_etiqueta(client):
    autenticar_admin(client)
    _crear_servidor_completo(client, "srv-tagged", etiquetas="finanzas, backup")
    pagina = client.get("/buscar?q=finanzas")
    assert pagina.status_code == 200
    assert "srv-tagged" in pagina.text


def test_notas_seguras_cifradas_y_reveladas(client):
    autenticar_admin(client)
    sid = _crear_servidor_completo(client, "srv-notas")

    # Guardar notas
    csrf = csrf_de(client, f"/activos/fisico/{sid}/notas")
    r = client.post(f"/activos/fisico/{sid}/notas",
                    data={"contenido": "VPN: usuario vpn / token ABC123", "csrf_token": csrf})
    assert r.status_code == 303

    db = sesion_bd()
    try:
        from app.models import ServidorFisico
        from app.security.crypto import descifrar

        s = db.get(ServidorFisico, sid)
        assert s.notas_cifradas is not None
        assert b"token ABC123" not in s.notas_cifradas      # cifradas en reposo
        assert descifrar(s.notas_cifradas) == "VPN: usuario vpn / token ABC123"
    finally:
        db.close()

    # Revelar (auditado)
    csrf = csrf_de(client, f"/servidores/{sid}")
    rev = client.post(f"/activos/fisico/{sid}/notas/revelar", data={"csrf_token": csrf})
    assert rev.status_code == 200
    assert rev.json()["notas"] == "VPN: usuario vpn / token ABC123"
    assert rev.headers["cache-control"] == "no-store"

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "nota_revelada")) is not None
    finally:
        db.close()


def test_notas_no_aparecen_en_el_detalle(client):
    autenticar_admin(client)
    sid = _crear_servidor_completo(client, "srv-notas2")
    csrf = csrf_de(client, f"/activos/fisico/{sid}/notas")
    client.post(f"/activos/fisico/{sid}/notas",
                data={"contenido": "SECRETO-EN-NOTA", "csrf_token": csrf})
    # El HTML del detalle nunca contiene el texto de la nota (solo se revela por API)
    assert "SECRETO-EN-NOTA" not in client.get(f"/servidores/{sid}").text


def test_reconciliador_aplica_columnas_nuevas_en_bd_existente():
    # La tabla servidores_fisicos pre-creada con columnas mínimas obtiene todas
    # las nuevas (hardware/estado/etiquetas) sin recrear la BD.
    import os
    import tempfile

    from sqlalchemy import inspect, text

    from app.config import reset_settings
    from app.database import Base, get_engine, reset_engine

    os.environ["PASSWD_DATA_DIR"] = tempfile.mkdtemp()
    os.environ["PASSWD_COOKIE_SECURE"] = "false"
    os.environ.pop("PASSWD_DATABASE_URL", None)
    reset_settings()
    reset_engine()
    engine = get_engine()
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE servidores_fisicos "
            "(id INTEGER PRIMARY KEY, nombre VARCHAR(120), tipo VARCHAR(32))"
        ))

    import app.models  # noqa: F401
    from app.schema_sync import reconciliar_esquema

    Base.metadata.create_all(engine)
    reconciliar_esquema(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("servidores_fisicos")}
    for nueva in ("ram", "cpu", "almacenamiento", "numero_serie", "garantia_hasta", "proveedor", "estado", "etiquetas"):
        assert nueva in cols, nueva
    reset_engine()
    reset_settings()
