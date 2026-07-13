"""Pruebas de las mejoras de la Ola 1 del análisis (`docs/analisis-mejoras.md`).

SEC-3: IP real del cliente tras un proxy de confianza (X-Forwarded-For).
SEC-5: el presupuesto anti-exfiltración de notas e historial usa el backend
       compartido en BD (antes caía siempre a memoria por no pasar ``db=``).
SEC-6: la revocación de sesión de un usuario desactivado persiste también en
       la vía JSON (antes se perdía con el rollback del 401).
ESC-2: la búsqueda filtra por acceso por objeto ANTES de aplicar el límite,
       de modo que un analista encuentra sus activos concedidos aunque haya
       más de 50 coincidencias en el inventario.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    autenticar_admin,
    csrf_de,
    login_password,
    sesion_bd,
)
from tests.test_accesos import _conceder, _preparar_analista
from tests.test_credenciales import _crear_credencial
from tests.test_inventario import _crear_servidor

# ---------------------------------------------------------------------------
# SEC-5 — presupuesto anti-exfiltración compartido (backend en BD)
# ---------------------------------------------------------------------------


def _guardar_notas(client, servidor_id: int, contenido: str = "secreto") -> None:
    csrf = csrf_de(client, f"/activos/fisico/{servidor_id}/notas")
    r = client.post(f"/activos/fisico/{servidor_id}/notas",
                    data={"contenido": contenido, "csrf_token": csrf})
    assert r.status_code == 303


def test_revelado_de_notas_usa_el_backend_compartido_en_bd(client, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    autenticar_admin(client)
    sid = _crear_servidor(client, "srv-notas-tasa")
    _guardar_notas(client, sid)

    monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")
    monkeypatch.setattr(get_settings(), "reveal_rate_limit", 1)

    csrf = csrf_de(client, f"/servidores/{sid}")
    assert client.post(f"/activos/fisico/{sid}/notas/revelar",
                       data={"csrf_token": csrf}).status_code == 200
    # Si el conteo viviera solo en la memoria del proceso, esto lo borraría y
    # el segundo revelado pasaría (el fallo que corrige la Ola 1):
    ratelimit.reiniciar()
    assert client.post(f"/activos/fisico/{sid}/notas/revelar",
                       data={"csrf_token": csrf}).status_code == 429

    db = sesion_bd()
    try:
        from app.models import EventoTasa

        eventos = db.scalar(select(func.count(EventoTasa.id))
                            .where(EventoTasa.clave.like("revelar:%")))
        assert eventos == 1  # el intento permitido quedó contabilizado en BD
    finally:
        db.close()


def test_revelado_de_historial_usa_el_backend_compartido_en_bd(client, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    autenticar_admin(client)
    sid = _crear_servidor(client, "srv-historial-tasa")
    _crear_credencial(client, "fisico", sid)

    db = sesion_bd()
    try:
        from app.models import Credencial

        cred_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    # Una rotación deja una entrada de historial.
    csrf = csrf_de(client, f"/credenciales/{cred_id}/editar")
    r = client.post(f"/credenciales/{cred_id}/editar", data={
        "usuario_acceso": "root", "password": "RotacionDePrueba#1", "servicio": "SSH",
        "puerto": "22", "descripcion": "", "csrf_token": csrf,
    })
    assert r.status_code == 303

    db = sesion_bd()
    try:
        from app.models import HistorialCredencial

        hist_id = db.scalar(select(HistorialCredencial.id))
    finally:
        db.close()

    monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")
    monkeypatch.setattr(get_settings(), "reveal_rate_limit", 1)

    csrf = csrf_de(client, f"/credenciales/{cred_id}/editar")
    ruta = f"/credenciales/{cred_id}/historial/{hist_id}/revelar"
    assert client.post(ruta, data={"csrf_token": csrf}).status_code == 200
    ratelimit.reiniciar()  # borra la memoria; el conteo debe sobrevivir en BD
    assert client.post(ruta, data={"csrf_token": csrf}).status_code == 429


def test_revelado_de_notas_json_usa_el_backend_compartido_en_bd(client, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    autenticar_admin(client)
    sid = _crear_servidor(client, "srv-notas-json-tasa")
    _guardar_notas(client, sid)

    monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")
    monkeypatch.setattr(get_settings(), "reveal_rate_limit", 1)

    csrf = client.get("/api/web/session").json()["csrf_token"]
    cabeceras = {"X-CSRF-Token": csrf}
    ruta = f"/api/web/activos/fisico/{sid}/notas/revelar"
    assert client.post(ruta, headers=cabeceras).status_code == 200
    ratelimit.reiniciar()
    assert client.post(ruta, headers=cabeceras).status_code == 429


# ---------------------------------------------------------------------------
# SEC-6 — la revocación de sesión persiste en la vía JSON
# ---------------------------------------------------------------------------


def test_revocacion_json_de_usuario_desactivado_persiste(client):
    autenticar_admin(client)

    # Desactivación directa en BD (sin pasar por /usuarios, que ya revoca
    # sesiones): simula una desactivación externa con la sesión aún viva.
    db = sesion_bd()
    try:
        from app.models import Usuario

        usuario = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        usuario.activo = False
        db.commit()
    finally:
        db.close()

    assert client.get("/api/web/buscar", params={"q": "algo"}).status_code == 401

    db = sesion_bd()
    try:
        from app.models import SesionWeb

        revocadas = db.scalar(
            select(func.count(SesionWeb.id)).where(SesionWeb.revocada_en.is_not(None))
        )
        assert revocadas >= 1  # la marca sobrevivió al rollback del 401
    finally:
        db.close()


# ---------------------------------------------------------------------------
# SEC-3 — IP real tras un proxy de confianza
# ---------------------------------------------------------------------------


@pytest.fixture()
def aplicacion_tras_proxy(tmp_path, monkeypatch):
    """Aplicación con PASSWD_TRUSTED_PROXIES activo (proxy de confianza)."""
    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWD_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("PASSWD_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("PASSWD_ADMIN_PASSWORD", ADMIN_PASS_INICIAL)
    monkeypatch.setenv("PASSWD_TRUSTED_PROXIES", "*")
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


def test_auditoria_registra_la_ip_real_tras_el_proxy(aplicacion_tras_proxy):
    cli = TestClient(aplicacion_tras_proxy, follow_redirects=False,
                     headers={"X-Forwarded-For": "203.0.113.7"})
    login_password(cli, ADMIN_USER, "clave-incorrecta")

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        registro = db.scalar(
            select(RegistroAuditoria).where(RegistroAuditoria.direccion_ip == "203.0.113.7")
        )
        assert registro is not None  # la bitácora vio la IP del cliente, no la del proxy
    finally:
        db.close()


def test_sin_proxies_de_confianza_se_ignora_x_forwarded_for(client):
    # Con la variable vacía (fixture normal) la cabecera no debe influir.
    client.headers["X-Forwarded-For"] = "198.51.100.99"
    login_password(client, ADMIN_USER, "clave-incorrecta")

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        registro = db.scalar(
            select(RegistroAuditoria).where(RegistroAuditoria.direccion_ip == "198.51.100.99")
        )
        assert registro is None  # cabecera de un cliente directo: no confiable
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ESC-2 — la búsqueda filtra por acceso ANTES del límite
# ---------------------------------------------------------------------------


def test_busqueda_analista_encuentra_su_activo_mas_alla_del_limite(client, crear_cliente):
    autenticar_admin(client)
    # 55 coincidencias que llenan el LIMIT 50 antes que el activo concedido
    # (alfabéticamente el último).
    for i in range(55):
        _crear_servidor(client, f"lote-busqueda-{i:03d}")
    objetivo = _crear_servidor(client, "lote-busqueda-zzz")

    cli, uid = _preparar_analista(client, crear_cliente)
    assert _conceder(client, "fisico", objetivo, uid, nivel="ver").status_code == 303

    # Web Jinja
    pagina = cli.get("/buscar?q=lote-busqueda")
    assert pagina.status_code == 200
    assert "lote-busqueda-zzz" in pagina.text
    assert "lote-busqueda-000" not in pagina.text  # lo no concedido sigue oculto

    # API JSON
    r = cli.get("/api/web/buscar", params={"q": "lote-busqueda"})
    assert r.status_code == 200
    nombres = [s["nombre"] for s in r.json()["servidores"]]
    assert nombres == ["lote-busqueda-zzz"]

    # El admin sigue viendo el lote completo hasta el límite habitual.
    pagina_admin = client.get("/buscar?q=lote-busqueda")
    assert "lote-busqueda-000" in pagina_admin.text
