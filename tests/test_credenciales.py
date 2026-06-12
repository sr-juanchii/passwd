"""Pruebas de credenciales: cifrado en reposo, revelado auditado y RBAC."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.conftest import (
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    sesion_bd,
)
from tests.test_inventario import _crear_hipervisor, _crear_servidor, _crear_vm

CLAVE_SECRETA = "SuperClaveDelServidor#2026"


def _crear_credencial(client, activo: str, activo_id: int, usuario_acceso: str = "root") -> None:
    csrf = csrf_de(client, f"/credenciales/nueva?activo={activo}&activo_id={activo_id}")
    respuesta = client.post("/credenciales/nueva", data={
        "activo": activo, "activo_id": str(activo_id), "usuario_acceso": usuario_acceso,
        "password": CLAVE_SECRETA, "servicio": "SSH", "puerto": "22",
        "descripcion": "Acceso de administración", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó la credencial: {respuesta.status_code}"


def test_credenciales_en_los_tres_niveles_y_cifrado(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-fisico", "funcion_unica")
    host = _crear_servidor(client, "srv-host", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-01")
    vm = _crear_vm(client, hipervisor, "vm-app")

    _crear_credencial(client, "fisico", fisico, "root")
    _crear_credencial(client, "hipervisor", hipervisor, "admin-pve")
    _crear_credencial(client, "vm", vm, "ubuntu")

    db = sesion_bd()
    try:
        from app.models import Credencial
        from app.security.crypto import descifrar

        credenciales = db.scalars(select(Credencial)).all()
        assert len(credenciales) == 3
        tipos = {c.tipo_activo for c in credenciales}
        assert tipos == {"fisico", "hipervisor", "vm"}
        for credencial in credenciales:
            assert CLAVE_SECRETA.encode() not in credencial.password_cifrada  # cifrada en reposo
            assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA
    finally:
        db.close()


def test_revelar_devuelve_la_clave_y_queda_auditado(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-revelar", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)

    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    csrf = csrf_de(client, f"/servidores/{fisico}")
    respuesta = client.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf})
    assert respuesta.status_code == 200
    assert respuesta.json()["password"] == CLAVE_SECRETA
    assert respuesta.headers["cache-control"] == "no-store"

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        eventos = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "credencial_revelada")).all()
        assert len(eventos) == 1
        assert eventos[0].username == "admin"
    finally:
        db.close()


def test_editar_con_password_en_blanco_conserva_la_actual(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-editar", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)

    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    csrf = csrf_de(client, f"/credenciales/{credencial_id}/editar")
    respuesta = client.post(f"/credenciales/{credencial_id}/editar", data={
        "usuario_acceso": "root-renombrado", "password": "", "servicio": "SSH",
        "puerto": "2222", "descripcion": "Puerto cambiado", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303

    db = sesion_bd()
    try:
        from app.models import Credencial
        from app.security.crypto import descifrar

        credencial = db.get(Credencial, credencial_id)
        assert credencial.usuario_acceso == "root-renombrado"
        assert credencial.puerto == 2222
        assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA  # sin cambios
    finally:
        db.close()


def test_auditor_no_puede_revelar_ni_gestionar(client, crear_cliente):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-rbac", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)
    clave_temporal = crear_usuario(client, "auditora", "auditor")

    cliente_auditor = crear_cliente()
    autenticar_usuario_nuevo(cliente_auditor, "auditora", clave_temporal)

    # Puede ver el inventario, pero sin botones de gestión
    panel = cliente_auditor.get("/")
    assert panel.status_code == 200
    assert "+ Servidor físico" not in panel.text

    detalle = cliente_auditor.get(f"/servidores/{fisico}")
    assert detalle.status_code == 200
    assert "Oculta (rol sin permiso)" in detalle.text

    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial_id = db.scalar(select(Credencial.id))
    finally:
        db.close()

    csrf = csrf_de(cliente_auditor, f"/servidores/{fisico}")
    respuesta = cliente_auditor.post(f"/credenciales/{credencial_id}/revelar", data={"csrf_token": csrf})
    assert respuesta.status_code == 403

    respuesta = cliente_auditor.post("/servidores/nuevo", data={
        "nombre": "no-permitido", "tipo": "funcion_unica", "csrf_token": csrf,
    })
    assert respuesta.status_code == 403

    # El intento denegado queda en auditoría a pesar del error
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        denegados = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "acceso_denegado",
            RegistroAuditoria.username == "auditora")).all()
        assert len(denegados) >= 2
    finally:
        db.close()


def test_restriccion_un_solo_activo_por_credencial(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-check", "funcion_unica")
    host = _crear_servidor(client, "srv-check-host", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-check")

    db = sesion_bd()
    try:
        from app.models import Credencial
        from app.security.crypto import cifrar

        db.add(Credencial(
            usuario_acceso="x", password_cifrada=cifrar("y"),
            servidor_fisico_id=fisico, hipervisor_id=hipervisor,  # dos activos: inválido
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
