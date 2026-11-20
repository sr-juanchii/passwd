"""Avisos previos de las roturas de la 2.0 (R1, R4 y R7).

El principio §4 de ``docs/plan-v2.0.md`` dice que ninguna de las ocho roturas se
publica sin aviso previo en la 1.3. Estas pruebas comprueban que el aviso existe
y, tan importante como eso, que **no aparece donde no toca**: un aviso que sale
siempre deja de leerse, y entonces no avisa de nada.
"""

from __future__ import annotations

import logging

from tests.conftest import autenticar_admin, csrf_de
from tests.test_api import _crear_token

BANNER = "se retira en la versión 2.0"


def _capturar(nombre_logger: str):
    """Manejador propio sobre un logger concreto.

    No se usa ``caplog``: depende de que la propagación siga activa y basta con
    que otra prueba de la suite toque la configuración de logging para que
    capture en vacío y el control pase sin verificar nada.
    """
    mensajes: list[str] = []

    class _Captura(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            mensajes.append(registro.getMessage())

    return logging.getLogger(nombre_logger), _Captura(), mensajes


# ---------------------------------------------------------------------------
# R1 — la interfaz clásica se retira
# ---------------------------------------------------------------------------


def test_las_rutas_clasicas_se_marcan_como_obsoletas(client):
    respuesta = client.get("/login")
    assert respuesta.status_code == 200
    assert respuesta.headers["Deprecation"] == "true"
    assert 'rel="deprecation"' in respuesta.headers["Link"]


def test_las_apis_y_los_estaticos_no_se_marcan(client):
    """El aviso es de la interfaz clásica, no del backend entero."""
    for ruta in ("/api/web/session", "/healthz", "/static/styles.css"):
        respuesta = client.get(ruta)
        assert "Deprecation" not in respuesta.headers, f"{ruta} no debería marcarse"


def test_la_api_del_siem_no_se_marca_como_obsoleta(client):
    """`/api/v1` sigue vivo en la 2.0: marcarlo sería mentir a las integraciones."""
    autenticar_admin(client)
    token = _crear_token(client, "siem-avisos")
    respuesta = client.get("/api/v1/auditoria", headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == 200
    assert "Deprecation" not in respuesta.headers


def test_la_interfaz_clasica_muestra_el_banner_antes_de_entrar(client):
    """Quien entra por el acceso clásico lo ve sin haber iniciado sesión."""
    assert BANNER in client.get("/login").text


def test_el_banner_sigue_estando_con_la_sesion_abierta(client):
    autenticar_admin(client)
    assert BANNER in client.get("/").text


# ---------------------------------------------------------------------------
# R4 — configuración obsoleta
# ---------------------------------------------------------------------------


def test_no_se_avisa_de_configuracion_obsoleta_si_no_se_usa(monkeypatch):
    """Una instalación limpia no debe ver ningún aviso."""
    from app.config import obsoletas_en_uso

    monkeypatch.delenv("PASSWD_SMTP_TLS", raising=False)
    monkeypatch.delenv("PASSWD_NOTIFY_ENABLED", raising=False)
    assert obsoletas_en_uso() == []


def test_se_detecta_cada_herencia_obsoleta_con_su_sustituta(monkeypatch):
    from app.config import obsoletas_en_uso

    monkeypatch.setenv("PASSWD_SMTP_TLS", "true")
    monkeypatch.setenv("PASSWD_NOTIFY_ENABLED", "true")
    monkeypatch.delenv("PASSWD_SMTP_SECURITY", raising=False)
    monkeypatch.delenv("PASSWD_SMTP_ENABLED", raising=False)
    detectadas = dict(obsoletas_en_uso())
    assert detectadas == {"SMTP_TLS": "SMTP_SECURITY", "NOTIFY_ENABLED": "SMTP_ENABLED"}


def test_no_se_avisa_cuando_la_variable_nueva_ya_esta_definida(monkeypatch):
    """Con las dos puestas manda la nueva: la herencia no decide nada.

    Importa porque `PASSWD_NOTIFY_ENABLED` NO es una variable muerta: gobierna
    las alertas de seguridad a los administradores. Avisar de ella a quien ya
    define `PASSWD_SMTP_ENABLED` le invitaría a borrarla y quedarse sin alertas.
    """
    from app.config import obsoletas_en_uso

    monkeypatch.setenv("PASSWD_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("PASSWD_SMTP_ENABLED", "true")
    monkeypatch.setenv("PASSWD_SMTP_TLS", "true")
    monkeypatch.setenv("PASSWD_SMTP_SECURITY", "starttls")
    assert obsoletas_en_uso() == []


def test_notify_enabled_sigue_gobernando_las_alertas(monkeypatch):
    """La variable conserva su significado propio aunque la herencia se retire."""
    from app.config import Settings

    monkeypatch.setenv("PASSWD_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("PASSWD_SMTP_ENABLED", "false")
    assert Settings().notify_enabled is True


def test_el_arranque_avisa_de_la_configuracion_obsoleta(tmp_path, monkeypatch):
    """El aviso sale al crear la aplicación, que es cuando alguien lo lee."""
    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_COOKIE_SECURE", "false")
    monkeypatch.setenv("PASSWD_SMTP_TLS", "false")
    monkeypatch.delenv("PASSWD_SMTP_SECURITY", raising=False)
    monkeypatch.delenv("PASSWD_DATABASE_URL", raising=False)

    from app.config import reset_settings
    from app.database import reset_engine

    reset_settings()
    reset_engine()
    logger, manejador, mensajes = _capturar("app.main")
    logger.addHandler(manejador)
    nivel = logger.level
    logger.setLevel(logging.WARNING)
    try:
        from app.main import create_app

        create_app()
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel)
        reset_engine()
        reset_settings()

    avisos = [m for m in mensajes if "PASSWD_SMTP_TLS" in m]
    assert avisos, mensajes
    # El aviso nombra la herencia y la variable que hay que definir, no pide
    # sustituir la antigua a ciegas.
    assert "PASSWD_SMTP_SECURITY" in avisos[0]
    assert "2.0" in avisos[0]


# ---------------------------------------------------------------------------
# R7 — /api/v1/inventario cambia de comportamiento
# ---------------------------------------------------------------------------


def test_se_avisa_de_que_el_inventario_del_siem_cambiara(client):
    from app.routes import api as modulo_api

    autenticar_admin(client)
    token = _crear_token(client, "siem-inventario")

    modulo_api._aviso_inventario_emitido = False
    logger, manejador, mensajes = _capturar("app.routes.api")
    logger.addHandler(manejador)
    nivel = logger.level
    logger.setLevel(logging.WARNING)
    try:
        respuesta = client.get("/api/v1/inventario",
                               headers={"Authorization": f"Bearer {token}"})
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel)

    assert respuesta.status_code == 200
    assert any("paginará" in m for m in mensajes), mensajes


def test_el_aviso_del_inventario_no_cambia_la_respuesta(client):
    """La serie 1.x mantiene el contrato de /api/v1 sin tocar.

    Añadir una clave de aviso al JSON rompería a un cliente con validación
    estricta de esquema, que es justo a quien el aviso pretende ayudar.
    """
    autenticar_admin(client)
    token = _crear_token(client, "siem-contrato")
    cuerpo = client.get("/api/v1/inventario",
                        headers={"Authorization": f"Bearer {token}"}).json()
    assert set(cuerpo) == {
        "servidores_fisicos", "hipervisores", "maquinas_virtuales", "dispositivos_red",
    }


def test_el_aviso_del_inventario_sale_una_vez_por_proceso(client):
    """Un aviso por petición inundaría la bitácora operativa y acabaría filtrado."""
    from app.routes import api as modulo_api

    autenticar_admin(client)
    token = _crear_token(client, "siem-una-vez")
    cabeceras = {"Authorization": f"Bearer {token}"}

    modulo_api._aviso_inventario_emitido = False
    logger, manejador, mensajes = _capturar("app.routes.api")
    logger.addHandler(manejador)
    nivel = logger.level
    logger.setLevel(logging.WARNING)
    try:
        for _ in range(3):
            client.get("/api/v1/inventario", headers=cabeceras)
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel)

    assert len([m for m in mensajes if "paginará" in m]) == 1


def test_no_se_avisa_cuando_la_llamada_ya_pagina(client):
    """Quien ya usa `limit` no va a notar el cambio: no hay nada que avisarle."""
    from app.routes import api as modulo_api

    autenticar_admin(client)
    token = _crear_token(client, "siem-paginado")
    csrf_de(client, "/")  # la sesión sigue viva

    modulo_api._aviso_inventario_emitido = False
    logger, manejador, mensajes = _capturar("app.routes.api")
    logger.addHandler(manejador)
    nivel = logger.level
    logger.setLevel(logging.WARNING)
    try:
        client.get("/api/v1/inventario?limit=50",
                   headers={"Authorization": f"Bearer {token}"})
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel)

    assert not [m for m in mensajes if "paginará" in m]
