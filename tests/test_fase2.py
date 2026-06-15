"""Pruebas de la Fase 2 — inventario más rico (hardware, estado, etiquetas)."""

from __future__ import annotations

from sqlalchemy import func, select

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


def test_historial_de_contrasenas(client):
    autenticar_admin(client)
    from tests.test_credenciales import _crear_credencial

    sid = _crear_servidor_completo(client, "srv-hist")
    _crear_credencial(client, "fisico", sid)  # password inicial = CLAVE_SECRETA

    db = sesion_bd()
    try:
        from app.models import Credencial

        cred_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    # Rotar dos veces → dos entradas de historial (la inicial y la 2ª).
    for nueva in ("PrimeraRotacion#1", "SegundaRotacion#2"):
        csrf = csrf_de(client, f"/credenciales/{cred_id}/editar")
        r = client.post(f"/credenciales/{cred_id}/editar", data={
            "usuario_acceso": "root", "password": nueva, "servicio": "SSH",
            "puerto": "22", "descripcion": "", "csrf_token": csrf,
        })
        assert r.status_code == 303

    db = sesion_bd()
    try:
        from app.models import Credencial, HistorialCredencial
        from app.security.crypto import descifrar

        entradas = db.scalars(select(HistorialCredencial).where(
            HistorialCredencial.credencial_id == cred_id)).all()
        assert len(entradas) == 2
        claves = {descifrar(e.password_cifrada) for e in entradas}
        from tests.test_credenciales import CLAVE_SECRETA

        assert CLAVE_SECRETA in claves and "PrimeraRotacion#1" in claves
        # La credencial vigente tiene la última
        assert descifrar(db.get(Credencial, cred_id).password_cifrada) == "SegundaRotacion#2"

        hist_id = entradas[0].id
    finally:
        db.close()

    # Revelar una entrada del historial queda auditado
    csrf = csrf_de(client, f"/credenciales/{cred_id}/editar")
    rev = client.post(f"/credenciales/{cred_id}/historial/{hist_id}/revelar", data={"csrf_token": csrf})
    assert rev.status_code == 200
    assert rev.json()["password"] in ("SegundaRotacion#2", "PrimeraRotacion#1", "SuperClaveDelServidor#2026")
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "historial_revelado")) is not None
    finally:
        db.close()


def test_historial_respeta_tope_configurable(client):
    autenticar_admin(client)
    from app.config import get_settings
    from tests.test_credenciales import _crear_credencial

    sid = _crear_servidor_completo(client, "srv-tope")
    _crear_credencial(client, "fisico", sid)
    db = sesion_bd()
    try:
        from app.models import Credencial

        cred_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    settings = get_settings()
    original = settings.password_history_max
    settings.password_history_max = 2
    try:
        for i in range(4):
            csrf = csrf_de(client, f"/credenciales/{cred_id}/editar")
            client.post(f"/credenciales/{cred_id}/editar", data={
                "usuario_acceso": "root", "password": f"Rotacion-{i}-xyz", "servicio": "SSH",
                "puerto": "22", "descripcion": "", "csrf_token": csrf,
            })
        db = sesion_bd()
        try:
            from app.models import HistorialCredencial

            n = db.scalar(select(func.count(HistorialCredencial.id)).where(
                HistorialCredencial.credencial_id == cred_id))
            assert n == 2  # podado al tope
        finally:
            db.close()
    finally:
        settings.password_history_max = original


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
