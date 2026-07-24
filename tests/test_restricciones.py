"""Pruebas de los activos restringidos a administradores.

Un administrador marca un servidor, hipervisor o dispositivo como ``restringido``:
- El OPERADOR deja de verlo (404 en detalle; fuera de listado, búsqueda y export).
- El AUDITOR sí lo ve (supervisión) pero nunca revela contraseñas.
- El ANALISTA solo lo ve con concesión explícita (la concesión prevalece).
- Las VMs heredan la restricción de su hipervisor.
Solo el administrador puede cambiar la marca (permiso ``inventario.restringir``).
"""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_credenciales import _crear_credencial
from tests.test_inventario import _crear_hipervisor, _crear_servidor, _crear_vm


def _restringir(admin_client, tipo_url: str, activo_id: int, nombre: str, campos: dict) -> None:
    """Reenvía el formulario de edición del activo con restringido=1."""
    csrf = csrf_de(admin_client, f"/{tipo_url}/{activo_id}/editar")
    datos = {"nombre": nombre, "restringido": "1", "csrf_token": csrf, **campos}
    r = admin_client.post(f"/{tipo_url}/{activo_id}/editar", data=datos)
    assert r.status_code == 303, f"No se restringió: {r.status_code}"


def _id_credencial() -> int:
    db = sesion_bd()
    try:
        from app.models import Credencial

        return db.scalar(select(Credencial.id))
    finally:
        db.close()


def test_operador_no_ve_servidor_restringido(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-secreto")
    _crear_credencial(client, "fisico", servidor)
    _restringir(client, "servidores", servidor, "srv-secreto",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})

    clave = crear_usuario(client, "oper1", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper1", clave)

    # Detalle: 404 (no filtra existencia)
    assert op.get(f"/servidores/{servidor}").status_code == 404
    # Dashboard: no aparece
    panel = op.get("/")
    assert "srv-secreto" not in panel.text
    # No puede editarlo ni eliminarlo (404)
    assert op.get(f"/servidores/{servidor}/editar").status_code == 404
    # No puede crear credenciales en él
    assert op.get(f"/credenciales/nueva?activo=fisico&activo_id={servidor}").status_code == 404


def test_auditor_si_ve_restringido_pero_no_revela(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-auditado")
    _crear_credencial(client, "fisico", servidor)
    _restringir(client, "servidores", servidor, "srv-auditado",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})
    credencial_id = _id_credencial()

    clave = crear_usuario(client, "aud1", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "aud1", clave)

    # El auditor SÍ ve el activo restringido (supervisión)
    detalle = aud.get(f"/servidores/{servidor}")
    assert detalle.status_code == 200
    assert "srv-auditado" in detalle.text
    # Aparece en su dashboard
    assert "srv-auditado" in aud.get("/").text
    # Pero no puede revelar la contraseña (como cualquier credencial)
    csrf = csrf_de(aud, f"/servidores/{servidor}")
    assert aud.post(f"/credenciales/{credencial_id}/revelar",
                    data={"csrf_token": csrf}).status_code == 403


def test_operador_no_puede_revelar_ni_gestionar_restringido(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-op-bloqueado")
    _crear_credencial(client, "fisico", servidor)
    _restringir(client, "servidores", servidor, "srv-op-bloqueado",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})
    credencial_id = _id_credencial()

    clave = crear_usuario(client, "oper2", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper2", clave)

    # Revelar/copiar → 404 (ni siquiera sabe que existe)
    # El CSRF hay que sacarlo de una página que el operador sí pueda ver.
    csrf = csrf_de(op, "/")
    assert op.post(f"/credenciales/{credencial_id}/revelar",
                   data={"csrf_token": csrf}).status_code == 404
    assert op.post(f"/credenciales/{credencial_id}/copiar",
                   data={"csrf_token": csrf}).status_code == 404
    # Eliminar credencial → 404
    assert op.post(f"/credenciales/{credencial_id}/eliminar",
                   data={"csrf_token": csrf}).status_code == 404


def test_vm_hereda_restriccion_del_hipervisor(client, crear_cliente):
    autenticar_admin(client)
    hipervisor = _crear_hipervisor(client, None, "pve-secreto")
    vm = _crear_vm(client, hipervisor, "vm-oculta")
    _restringir(client, "hipervisores", hipervisor, "pve-secreto",
                {"plataforma": "Proxmox VE", "version": "8.2"})

    clave = crear_usuario(client, "oper3", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper3", clave)

    # Ni el hipervisor ni su VM son visibles para el operador
    assert op.get(f"/hipervisores/{hipervisor}").status_code == 404
    assert op.get(f"/vms/{vm}").status_code == 404
    panel = op.get("/")
    assert "pve-secreto" not in panel.text and "vm-oculta" not in panel.text
    # El auditor sí ve ambos
    clave_a = crear_usuario(client, "aud3", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "aud3", clave_a)
    assert aud.get(f"/vms/{vm}").status_code == 200


def test_concesion_a_analista_prevalece_sobre_restriccion(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-analista")
    _crear_credencial(client, "fisico", servidor)
    _restringir(client, "servidores", servidor, "srv-analista",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})

    clave = crear_usuario(client, "ana1", "analista")
    ana = crear_cliente()
    autenticar_usuario_nuevo(ana, "ana1", clave)
    db = sesion_bd()
    try:
        from app.models import Usuario

        uid = db.scalar(select(Usuario.id).where(Usuario.username == "ana1"))
    finally:
        db.close()

    # Sin concesión: no lo ve
    assert ana.get(f"/servidores/{servidor}").status_code == 404
    # Con concesión explícita del admin: sí lo ve (la concesión prevalece)
    csrf = csrf_de(client, "/")
    r = client.post("/accesos/conceder", data={
        "tipo": "fisico", "activo_id": str(servidor), "usuario_id": str(uid),
        "nivel": "ver_credenciales", "expira_dias": "", "csrf_token": csrf,
    })
    assert r.status_code == 303
    assert ana.get(f"/servidores/{servidor}").status_code == 200


def test_solo_admin_puede_restringir(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-op-crea")

    clave = crear_usuario(client, "oper4", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper4", clave)

    # El operador edita el servidor e intenta marcarlo restringido: se ignora.
    csrf = csrf_de(op, f"/servidores/{servidor}/editar")
    r = op.post(f"/servidores/{servidor}/editar", data={
        "nombre": "srv-op-crea", "sistema_operativo": "Debian",
        "ip_gestion": "10.0.0.9", "restringido": "1", "csrf_token": csrf,
    })
    assert r.status_code == 303
    db = sesion_bd()
    try:
        from app.models import ServidorFisico

        assert db.get(ServidorFisico, servidor).restringido is False  # no se aplicó
    finally:
        db.close()


def test_busqueda_respeta_restriccion(client, crear_cliente):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-buscable-restr")
    _restringir(client, "servidores", servidor, "srv-buscable-restr",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})

    clave = crear_usuario(client, "oper5", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper5", clave)
    # El operador no lo encuentra
    assert "srv-buscable-restr" not in op.get("/buscar", params={"q": "buscable-restr"}).text
    # El admin sí
    assert "srv-buscable-restr" in client.get("/buscar", params={"q": "buscable-restr"}).text


def test_export_operador_excluye_restringidos(client, crear_cliente):
    autenticar_admin(client)
    visible = _crear_servidor(client, "srv-exportable")
    _crear_credencial(client, "fisico", visible, "root")
    restringido = _crear_servidor(client, "srv-no-exportable")
    _crear_credencial(client, "fisico", restringido, "admin-secreto")
    _restringir(client, "servidores", restringido, "srv-no-exportable",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})

    clave = crear_usuario(client, "oper6", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper6", clave)

    csrf = csrf_de(op, "/importar")
    texto = op.post("/exportar", data={"csrf_token": csrf}).text
    assert "srv-exportable" in texto
    assert "srv-no-exportable" not in texto
    assert "admin-secreto" not in texto  # tampoco su credencial

    # El admin sí exporta todo, con la columna restringido
    csrf = csrf_de(client, "/importar")
    texto_admin = client.post("/exportar", data={"csrf_token": csrf}).text
    assert "srv-no-exportable" in texto_admin
    assert "restringido" in texto_admin.splitlines()[0]  # cabecera


def test_api_web_marca_y_expone_restriccion(client, crear_cliente):
    autenticar_admin(client)
    csrf = client.get("/api/web/session").json()["csrf_token"]
    r = client.post("/api/web/servidores", headers={"X-CSRF-Token": csrf}, json={
        "nombre": "srv-json-restr", "sistema_operativo": "Debian", "restringido": True,
    })
    assert r.status_code == 200
    sid = r.json()["id"]

    datos = client.get(f"/api/web/servidores/{sid}").json()
    assert datos["restringido"] is True
    assert datos["puede_restringir"] is True

    # El operador no lo ve por la API JSON
    clave = crear_usuario(client, "oper7", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "oper7", clave)
    assert op.get(f"/api/web/servidores/{sid}").status_code == 404
    tablero = op.get("/api/web/dashboard").json()
    assert all(s["nombre"] != "srv-json-restr" for s in tablero["servidores"])
    # puede_restringir es False para el operador en un activo que sí ve
    csrf_op = op.get("/api/web/session").json()["csrf_token"]
    r = op.post("/api/web/servidores", headers={"X-CSRF-Token": csrf_op},
                json={"nombre": "srv-op-json", "restringido": True})
    sid_op = r.json()["id"]
    db = sesion_bd()
    try:
        from app.models import ServidorFisico

        assert db.get(ServidorFisico, sid_op).restringido is False  # operador no restringe
    finally:
        db.close()


def test_restriccion_queda_auditada(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-audit-restr")
    _restringir(client, "servidores", servidor, "srv-audit-restr",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        acciones = {r.accion for r in db.scalars(select(RegistroAuditoria)).all()}
        assert "activo_restriccion_cambiada" in acciones
    finally:
        db.close()


def test_respaldo_conserva_restriccion(client):
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-respaldo-restr")
    _restringir(client, "servidores", servidor, "srv-respaldo-restr",
                {"sistema_operativo": "Debian", "ip_gestion": "10.0.0.1"})

    from app import backup

    frase = "frase-de-respaldo-larga-2026"
    db = sesion_bd()
    try:
        datos = backup.exportar(db, frase)
        db.commit()
        backup.restaurar(db, datos, frase, sobrescribir=True)
        db.commit()
        from app.models import ServidorFisico

        restaurado = db.scalar(select(ServidorFisico).where(ServidorFisico.nombre == "srv-respaldo-restr"))
        assert restaurado is not None and restaurado.restringido is True
    finally:
        db.close()
