"""Pruebas del control de acceso por objeto (concesiones a analistas).

Verifican el aislamiento: un analista solo ve y usa los activos concedidos,
con el nivel concedido; lo demás responde 404 (sin filtrar existencia) o 403.
"""

from __future__ import annotations

import datetime

from sqlalchemy import func, select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_hipervisor, _crear_servidor, _crear_vm


def _id_usuario(username: str) -> int:
    db = sesion_bd()
    try:
        from app.models import Usuario

        return db.scalar(select(Usuario.id).where(Usuario.username == username))
    finally:
        db.close()


def _id_credencial() -> int:
    db = sesion_bd()
    try:
        from app.models import Credencial

        return db.scalar(select(Credencial.id))
    finally:
        db.close()


def _conceder(admin_client, tipo, activo_id, usuario_id, nivel="ver", expira_dias=""):
    csrf = csrf_de(admin_client, "/")
    return admin_client.post("/accesos/conceder", data={
        "tipo": tipo, "activo_id": str(activo_id), "usuario_id": str(usuario_id),
        "nivel": nivel, "expira_dias": expira_dias, "csrf_token": csrf,
    })


def _preparar_analista(admin_client, crear_cliente, username="analista1"):
    clave = crear_usuario(admin_client, username, "analista")
    cli = crear_cliente()
    autenticar_usuario_nuevo(cli, username, clave)
    return cli, _id_usuario(username)


def test_analista_sin_concesion_no_ve_nada(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-secreto", "funcion_unica")
    cli, _uid = _preparar_analista(client, crear_cliente)

    panel = cli.get("/")
    assert panel.status_code == 200
    assert "Mis accesos" in panel.text
    assert "No tienes accesos concedidos" in panel.text
    # Activo no concedido: 404 (no revela existencia)
    assert cli.get(f"/servidores/{servidor}").status_code == 404


def test_concesion_ver_permite_ver_pero_no_revelar(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-ver", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)
    cli, uid = _preparar_analista(client, crear_cliente)

    assert _conceder(client, "fisico", servidor, uid, nivel="ver").status_code == 303

    detalle = cli.get(f"/servidores/{servidor}")
    assert detalle.status_code == 200
    assert "root" in detalle.text  # ve el usuario de la credencial
    assert "sin permiso para esta credencial" in detalle.text  # pero no puede revelarla

    credencial_id = _id_credencial()
    csrf = csrf_de(cli, f"/servidores/{servidor}")
    assert cli.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf}).status_code == 403
    assert cli.post(f"/credenciales/{credencial_id}/copiar", data={"csrf_token": csrf}).status_code == 403


def test_concesion_ver_credenciales_permite_revelar_y_audita(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-cred", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)
    cli, uid = _preparar_analista(client, crear_cliente)
    assert _conceder(client, "fisico", servidor, uid, nivel="ver_credenciales").status_code == 303

    credencial_id = _id_credencial()
    csrf = csrf_de(cli, f"/servidores/{servidor}")
    respuesta = cli.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf})
    assert respuesta.status_code == 200
    assert respuesta.json()["password"] == CLAVE_SECRETA

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        evento = db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "credencial_revelada",
            RegistroAuditoria.username == "analista1"))
        assert evento is not None
        assert "vía concesión" in evento.detalle
    finally:
        db.close()


def test_activo_ajeno_responde_404(client, crear_cliente):
    autenticar_admin(client)
    a = _crear_servidor(client, "srv-a", "funcion_unica")
    b = _crear_servidor(client, "srv-b", "funcion_unica")
    _crear_credencial(client, "fisico", b)  # credencial en B
    cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", a, uid, nivel="ver_credenciales")  # solo A

    assert cli.get(f"/servidores/{a}").status_code == 200
    assert cli.get(f"/servidores/{b}").status_code == 404
    credencial_b = _id_credencial()
    csrf = csrf_de(cli, f"/servidores/{a}")
    # Revelar credencial de un activo no concedido: 404 (no filtra existencia)
    assert cli.post(f"/credenciales/{credencial_b}/revelar", data={"csrf_token": csrf}).status_code == 404


def test_revocacion_es_inmediata(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-revoca", "funcion_unica")
    cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", servidor, uid, nivel="ver")
    assert cli.get(f"/servidores/{servidor}").status_code == 200

    db = sesion_bd()
    try:
        from app.models import ConcesionAcceso

        concesion_id = db.scalar(select(ConcesionAcceso.id).where(ConcesionAcceso.usuario_id == uid))
    finally:
        db.close()

    csrf = csrf_de(client, "/")
    assert client.post(f"/accesos/{concesion_id}/revocar", data={"csrf_token": csrf}).status_code == 303
    assert cli.get(f"/servidores/{servidor}").status_code == 404


def test_concesion_expirada_se_ignora(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-exp", "funcion_unica")
    cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", servidor, uid, nivel="ver", expira_dias="7")
    assert cli.get(f"/servidores/{servidor}").status_code == 200

    db = sesion_bd()
    try:
        from app.models import ConcesionAcceso

        concesion = db.scalar(select(ConcesionAcceso).where(ConcesionAcceso.usuario_id == uid))
        concesion.expira_en = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=1)
        db.commit()
    finally:
        db.close()

    assert cli.get(f"/servidores/{servidor}").status_code == 404


def test_concesion_sin_herencia(client, crear_cliente):
    autenticar_admin(client)
    host = _crear_servidor(client, "srv-host-h", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-h")
    vm = _crear_vm(client, hipervisor, "vm-h")
    cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", host, uid, nivel="ver")  # solo el físico

    assert cli.get(f"/servidores/{host}").status_code == 200
    assert cli.get(f"/hipervisores/{hipervisor}").status_code == 404  # no hereda
    assert cli.get(f"/vms/{vm}").status_code == 404
    # El detalle del host no debe listar sus hipervisores para el analista
    assert "Hipervisores alojados" not in cli.get(f"/servidores/{host}").text


def test_upsert_actualiza_nivel(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-upsert", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)
    cli, uid = _preparar_analista(client, crear_cliente)

    _conceder(client, "fisico", servidor, uid, nivel="ver")
    _conceder(client, "fisico", servidor, uid, nivel="ver_credenciales")  # re-concesión

    db = sesion_bd()
    try:
        from app.models import ConcesionAcceso

        total = db.scalar(select(func.count(ConcesionAcceso.id)).where(ConcesionAcceso.usuario_id == uid))
        assert total == 1  # se actualizó, no se duplicó
    finally:
        db.close()

    credencial_id = _id_credencial()
    csrf = csrf_de(cli, f"/servidores/{servidor}")
    assert cli.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf}).status_code == 200


def test_solo_admin_gestiona_accesos(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-rbac-acc", "funcion_unica")
    cli, uid = _preparar_analista(client, crear_cliente)

    # El analista no puede conceder, ni gestionar inventario/usuarios/auditoría
    csrf = csrf_de(cli, "/")
    assert cli.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver", "csrf_token": csrf,
    }).status_code == 403
    assert cli.get("/usuarios").status_code == 403
    assert cli.get("/auditoria").status_code == 403
    assert cli.post("/servidores/nuevo", data={
        "nombre": "x", "tipo": "funcion_unica", "csrf_token": csrf,
    }).status_code == 403


def test_panel_accesos_visible_para_admin(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-panel", "funcion_unica")
    _cli, uid = _preparar_analista(client, crear_cliente)
    _conceder(client, "fisico", servidor, uid, nivel="ver")

    detalle = client.get(f"/servidores/{servidor}")
    assert detalle.status_code == 200
    assert "Accesos de analistas" in detalle.text   # el panel se renderiza
    assert "analista1" in detalle.text               # el analista concedido aparece


def test_operador_conserva_acceso_total(client, crear_cliente):
    # Regresión: el control por objeto no debe afectar a operador (ve y revela todo).
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-op", "funcion_unica")
    _crear_credencial(client, "fisico", servidor)
    clave = crear_usuario(client, "oper1", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper1", clave)

    assert op.get(f"/servidores/{servidor}").status_code == 200
    credencial_id = _id_credencial()
    csrf = csrf_de(op, f"/servidores/{servidor}")
    assert op.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf}).status_code == 200
