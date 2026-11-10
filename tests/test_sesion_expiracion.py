"""Expiración de sesión vista por la API JSON (lo que consume el frontend).

- ``GET /api/web/session`` es un sondeo: informa de los plazos y NO cuenta como
  actividad (no prolonga la sesión).
- ``POST /api/web/session/extender`` renueva la inactividad, nunca la vida máxima.
- Una cookie que ya no abre ninguna sesión recibe 401 con ``code=sesion_expirada``
  y la orden de borrarla, para que la interfaz no quede "abierta" sin sesión.
"""

from __future__ import annotations

import datetime

from sqlalchemy import select

from tests.conftest import autenticar_admin, sesion_bd


def _sesion_activa():
    from app.models import ETAPA_ACTIVA, SesionWeb

    db = sesion_bd()
    return db, db.scalar(select(SesionWeb).where(SesionWeb.etapa == ETAPA_ACTIVA))


def _envejecer(minutos: int) -> None:
    db, sesion = _sesion_activa()
    try:
        sesion.ultima_actividad = sesion.ultima_actividad - datetime.timedelta(minutes=minutos)
        db.commit()
    finally:
        db.close()


def test_session_informa_de_los_plazos(client):
    autenticar_admin(client)
    datos = client.get("/api/web/session").json()
    assert datos["authenticated"] is True
    plazos = datos["sesion"]
    assert 0 < plazos["idle_expires_in"] <= plazos["idle_timeout"] == 15 * 60
    assert 0 < plazos["absolute_expires_in"] <= 8 * 3600
    assert plazos["margin"] == 60
    assert datos["password_min_length"] == 12


def test_consultar_session_no_prolonga_la_sesion(client):
    autenticar_admin(client)
    _envejecer(10)
    for _ in range(3):
        restante = client.get("/api/web/session").json()["sesion"]["idle_expires_in"]
    assert restante <= 5 * 60  # sigue contando: el sondeo no es actividad

    # Una petición real sí renueva la ventana.
    assert client.get("/api/web/dashboard").status_code == 200
    assert client.get("/api/web/session").json()["sesion"]["idle_expires_in"] > 14 * 60


def test_extender_renueva_inactividad_pero_no_vida_maxima(client):
    autenticar_admin(client)
    csrf = client.get("/api/web/session").json()["csrf_token"]
    _envejecer(14)
    antes = client.get("/api/web/session").json()["sesion"]
    assert antes["idle_expires_in"] <= 60

    assert client.post("/api/web/session/extender").status_code == 403  # exige CSRF
    r = client.post("/api/web/session/extender", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    despues = r.json()["sesion"]
    assert despues["idle_expires_in"] > 14 * 60
    assert despues["absolute_expires_in"] <= antes["absolute_expires_in"]


def test_sesion_vencida_devuelve_401_con_codigo_y_borra_cookie(client):
    autenticar_admin(client)
    _envejecer(16)
    r = client.get("/api/web/dashboard")
    assert r.status_code == 401
    assert r.json()["code"] == "sesion_expirada"
    assert isinstance(r.json()["detail"], str)
    borrado = r.headers["set-cookie"]
    assert borrado.startswith("passwd_session=") and "Max-Age=0" in borrado

    # La revocación quedó persistida pese al error.
    from app.models import SesionWeb

    db = sesion_bd()
    try:
        assert db.scalar(select(SesionWeb.revocada_en).order_by(SesionWeb.id.desc())) is not None
    finally:
        db.close()


def test_session_con_cookie_vencida_la_borra(client):
    autenticar_admin(client)
    _envejecer(16)
    r = client.get("/api/web/session")
    assert r.status_code == 200 and r.json()["authenticated"] is False
    assert "Max-Age=0" in r.headers.get("set-cookie", "")


def test_sin_cookie_el_401_no_lleva_codigo_de_expiracion(client):
    r = client.get("/api/web/dashboard")
    assert r.status_code == 401
    assert r.json().get("code") is None
    assert "set-cookie" not in r.headers


def test_amortiguacion_nunca_supera_media_ventana(client):
    """Una amortiguación mayor que la inactividad no puede dejar caducar una
    sesión que está en uso."""
    from app.config import get_settings
    from app.security.sessions import plazos

    autenticar_admin(client)
    settings = get_settings()
    settings.session_idle_minutes = 2
    settings.activity_throttle_seconds = 3600
    db, sesion = _sesion_activa()
    try:
        assert plazos(sesion)["margin"] == 60
    finally:
        db.close()
