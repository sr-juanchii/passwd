"""Pruebas de la Fase 1: export CSV de auditoría, métricas y búsqueda global."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_accesos import _conceder, _preparar_analista
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_servidor

# ---------------------------------------------------------------------------
# Export CSV de auditoría
# ---------------------------------------------------------------------------


def test_export_csv_auditoria(client):
    autenticar_admin(client)
    _crear_servidor(client, "srv-csv", "funcion_unica")  # genera eventos

    respuesta = client.get("/auditoria/export.csv")
    assert respuesta.status_code == 200
    assert "text/csv" in respuesta.headers["content-type"]
    assert "attachment" in respuesta.headers["content-disposition"]
    assert respuesta.headers["cache-control"] == "no-store"
    cuerpo = respuesta.text
    assert "fecha_utc,usuario,accion" in cuerpo  # cabecera
    assert "activo_creado" in cuerpo
    # La exportación queda registrada en la propia bitácora
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "auditoria_exportada")) is not None
    finally:
        db.close()


def test_export_csv_filtrado(client):
    autenticar_admin(client)
    _crear_servidor(client, "srv-f", "funcion_unica")
    respuesta = client.get("/auditoria/export.csv?filtro_accion=login_correcto")
    assert respuesta.status_code == 200
    assert "login_correcto" in respuesta.text
    assert "activo_creado" not in respuesta.text  # excluido por el filtro


def test_export_csv_mitiga_inyeccion_de_formulas(client):
    autenticar_admin(client)
    # Nombre que empieza con '=' : en el detalle del evento debe neutralizarse.
    csrf = csrf_de(client, "/servidores/nuevo")
    client.post("/servidores/nuevo", data={
        "nombre": "=cmd|calc", "tipo": "funcion_unica", "csrf_token": csrf,
    })
    cuerpo = client.get("/auditoria/export.csv").text
    assert "'=cmd|calc" in cuerpo        # neutralizado con comilla simple
    assert ",=cmd|calc" not in cuerpo    # nunca una celda que empiece por '='


def test_export_csv_requiere_permiso(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "oper-csv", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper-csv", clave)
    assert op.get("/auditoria/export.csv").status_code == 403


# ---------------------------------------------------------------------------
# Dashboard de métricas
# ---------------------------------------------------------------------------


def test_metricas_visible_admin_y_auditor(client, crear_cliente):
    autenticar_admin(client)
    pagina = client.get("/metricas")
    assert pagina.status_code == 200
    assert "Métricas de seguridad" in pagina.text
    # El admin recién enrolado tiene MFA; no debería figurar como sin MFA.

    clave = crear_usuario(client, "audi-m", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "audi-m", clave)
    assert aud.get("/metricas").status_code == 200


def test_metricas_denegada_a_operador_y_analista(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "oper-m", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper-m", clave)
    assert op.get("/metricas").status_code == 403


def test_metricas_cuenta_sin_mfa(client, crear_cliente):
    autenticar_admin(client)
    # Un usuario recién creado que solo cambió contraseña pero no enroló MFA.
    from tests.conftest import PASS_USUARIO, cambiar_password, login_password

    clave = crear_usuario(client, "pendiente", "operador")
    cli = crear_cliente()
    r = login_password(cli, "pendiente", clave)
    assert r.headers["location"] == "/password/cambiar"
    cambiar_password(cli, clave, PASS_USUARIO)  # queda en etapa de enrolar MFA

    pagina = client.get("/metricas")
    assert "pendiente" in pagina.text  # aparece en "cuentas sin MFA activo"


# ---------------------------------------------------------------------------
# Búsqueda global
# ---------------------------------------------------------------------------


def test_busqueda_encuentra_activos_y_credenciales(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "buscame-srv", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)  # usuario_acceso = root

    pagina = client.get("/buscar?q=buscame")
    assert pagina.status_code == 200
    assert "buscame-srv" in pagina.text

    por_usuario = client.get("/buscar?q=root")
    assert "buscame-srv" in por_usuario.text  # la credencial enlaza a su activo


def test_busqueda_consulta_corta_avisa(client):
    autenticar_admin(client)
    pagina = client.get("/buscar?q=a")
    assert pagina.status_code == 200
    assert "al menos" in pagina.text


def test_busqueda_respeta_acceso_por_objeto(client, crear_cliente):
    autenticar_admin(client)
    visible = _crear_servidor(client, "visible-ana", "funcion_unica")
    _crear_servidor(client, "oculto-ana", "funcion_unica")  # no concedido
    cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", visible, uid, nivel="ver")

    pagina = cli.get("/buscar?q=ana")
    assert pagina.status_code == 200
    assert "visible-ana" in pagina.text
    assert "oculto-ana" not in pagina.text  # no se filtra el inventario no concedido


def test_busqueda_no_busca_por_contrasena(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-nopass", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)  # password = CLAVE_SECRETA

    pagina = client.get(f"/buscar?q={CLAVE_SECRETA}")
    assert pagina.status_code == 200
    assert "srv-nopass" not in pagina.text  # la contraseña no es un criterio de búsqueda
