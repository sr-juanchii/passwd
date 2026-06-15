"""Pruebas de la importación masiva de inventario por CSV."""

from __future__ import annotations

from sqlalchemy import func, select

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)

CSV_OK = """tipo,nombre,tipo_servidor,padre,activo_tipo,plataforma,version,sistema_operativo,ip,descripcion,estado,etiquetas,usuario_acceso,password,servicio,puerto
servidor,srv-imp,host_virtualizacion,,,,,Proxmox,10.0.0.6,Host,activo,producción,,,,
hipervisor,pve-imp,,srv-imp,,Proxmox VE,8.2,,10.0.0.7,Nodo,activo,,,,,
vm,vm-imp,,pve-imp,,,,Ubuntu 24.04,10.0.1.10,Correo,activo,correo,,,,
credencial,,,vm-imp,vm,,,,,Acceso,activo,,ubuntu,Sup3rClave!,SSH,22
"""


def _importar(client, contenido: str):
    csrf = csrf_de(client, "/importar")
    return client.post(
        "/importar",
        data={"csrf_token": csrf},
        files={"archivo": ("inventario.csv", contenido.encode("utf-8"), "text/csv")},
    )


def test_importacion_crea_jerarquia_y_credencial(client):
    autenticar_admin(client)
    r = _importar(client, CSV_OK)
    assert r.status_code == 200
    assert "4 de 4" in r.text

    db = sesion_bd()
    try:
        from app.models import Credencial, Hipervisor, MaquinaVirtual, ServidorFisico
        from app.security.crypto import descifrar

        s = db.scalar(select(ServidorFisico).where(ServidorFisico.nombre == "srv-imp"))
        assert s is not None and s.tipo == "host_virtualizacion"
        assert s.lista_etiquetas == ["producción"]
        assert db.scalar(select(Hipervisor).where(Hipervisor.nombre == "pve-imp")) is not None
        assert db.scalar(select(MaquinaVirtual).where(MaquinaVirtual.nombre == "vm-imp")) is not None
        cred = db.scalar(select(Credencial))
        assert cred.usuario_acceso == "ubuntu"
        assert descifrar(cred.password_cifrada) == "Sup3rClave!"  # cifrada al importar
    finally:
        db.close()


def test_importacion_informa_errores_por_fila_sin_abortar(client):
    autenticar_admin(client)
    csv_mixto = (
        "tipo,nombre,tipo_servidor,padre,activo_tipo,usuario_acceso,password\n"
        "servidor,srv-ok,funcion_unica,,,,\n"
        "hipervisor,pve-huerfano,,no-existe,,,\n"           # padre inexistente → error
        "vm,vm-huerfana,,tampoco-existe,,,\n"               # padre inexistente → error
    )
    r = _importar(client, csv_mixto)
    assert r.status_code == 200
    assert "1 de 3" in r.text
    assert "no encontrado" in r.text  # se informan los errores
    db = sesion_bd()
    try:
        from app.models import Hipervisor, ServidorFisico

        assert db.scalar(select(func.count(ServidorFisico.id))) == 1  # solo el válido
        assert db.scalar(select(func.count(Hipervisor.id))) == 0
    finally:
        db.close()


def test_importacion_queda_auditada(client):
    autenticar_admin(client)
    _importar(client, CSV_OK)
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "importacion_realizada")) is not None
    finally:
        db.close()


def test_importacion_requiere_gestionar(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "audi-imp", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "audi-imp", clave)
    assert aud.get("/importar").status_code == 403
