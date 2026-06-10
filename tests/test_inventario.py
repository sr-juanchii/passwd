"""Pruebas del inventario relacional físico → hipervisor → máquina virtual."""

from __future__ import annotations

from sqlalchemy import func, select

from tests.conftest import autenticar_admin, csrf_de, sesion_bd


def _crear_servidor(client, nombre: str, tipo: str) -> int:
    csrf = csrf_de(client, "/servidores/nuevo")
    respuesta = client.post("/servidores/nuevo", data={
        "nombre": nombre, "tipo": tipo, "descripcion": f"Descripción de {nombre}",
        "sistema_operativo": "Debian 12", "ubicacion": "Sala principal",
        "ip_gestion": "10.0.0.10", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó el servidor: {respuesta.status_code}"
    return int(respuesta.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def _crear_hipervisor(client, servidor_id: int, nombre: str) -> int:
    csrf = csrf_de(client, f"/servidores/{servidor_id}/hipervisores/nuevo")
    respuesta = client.post(f"/servidores/{servidor_id}/hipervisores/nuevo", data={
        "nombre": nombre, "plataforma": "Proxmox VE", "version": "8.2",
        "ip_gestion": "10.0.0.11", "descripcion": "Nodo de virtualización", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó el hipervisor: {respuesta.status_code}"
    return int(respuesta.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def _crear_vm(client, hipervisor_id: int, nombre: str) -> int:
    csrf = csrf_de(client, f"/hipervisores/{hipervisor_id}/vms/nueva")
    respuesta = client.post(f"/hipervisores/{hipervisor_id}/vms/nueva", data={
        "nombre": nombre, "sistema_operativo": "Ubuntu Server 24.04",
        "ip": "10.0.1.20", "descripcion": "Servidor de correo institucional", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó la VM: {respuesta.status_code}"
    return int(respuesta.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def test_jerarquia_completa_y_arbol_en_panel(client):
    autenticar_admin(client)

    _crear_servidor(client, "srv-nomina", "funcion_unica")
    host = _crear_servidor(client, "srv-virtual-01", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-nodo-01")
    vm = _crear_vm(client, hipervisor, "vm-correo")

    panel = client.get("/")
    assert panel.status_code == 200
    for texto in ("srv-nomina", "srv-virtual-01", "pve-nodo-01", "vm-correo",
                  "Servidor físico de función única", "host de virtualización"):
        assert texto in panel.text, f"Falta «{texto}» en el panel"

    detalle_vm = client.get(f"/vms/{vm}")
    assert detalle_vm.status_code == 200
    assert "pve-nodo-01" in detalle_vm.text  # relación VM → hipervisor
    assert "srv-virtual-01" in detalle_vm.text  # relación VM → servidor físico


def test_servidor_funcion_unica_no_admite_hipervisores(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-dedicado", "funcion_unica")

    respuesta = client.get(f"/servidores/{fisico}/hipervisores/nuevo")
    assert respuesta.status_code == 400

    csrf = csrf_de(client, f"/servidores/{fisico}")
    respuesta = client.post(f"/servidores/{fisico}/hipervisores/nuevo", data={
        "nombre": "intruso", "plataforma": "ESXi", "csrf_token": csrf,
    })
    assert respuesta.status_code == 400


def test_no_degradar_host_con_hipervisores(client):
    autenticar_admin(client)
    host = _crear_servidor(client, "srv-host", "host_virtualizacion")
    _crear_hipervisor(client, host, "pve-a")

    csrf = csrf_de(client, f"/servidores/{host}/editar")
    respuesta = client.post(f"/servidores/{host}/editar", data={
        "nombre": "srv-host", "tipo": "funcion_unica", "csrf_token": csrf,
    })
    assert respuesta.status_code == 400
    assert "hipervisores asociados" in respuesta.text


def test_nombre_de_servidor_duplicado_rechazado(client):
    autenticar_admin(client)
    _crear_servidor(client, "srv-repetido", "funcion_unica")

    csrf = csrf_de(client, "/servidores/nuevo")
    respuesta = client.post("/servidores/nuevo", data={
        "nombre": "SRV-REPETIDO", "tipo": "funcion_unica", "csrf_token": csrf,
    })
    assert respuesta.status_code == 400
    assert "Ya existe" in respuesta.text


def test_eliminacion_en_cascada(client):
    autenticar_admin(client)
    host = _crear_servidor(client, "srv-cascada", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-cascada")
    _crear_vm(client, hipervisor, "vm-cascada")

    csrf = csrf_de(client, f"/servidores/{host}")
    respuesta = client.post(f"/servidores/{host}/eliminar", data={"csrf_token": csrf})
    assert respuesta.status_code == 303

    db = sesion_bd()
    try:
        from app.models import Hipervisor, MaquinaVirtual, ServidorFisico

        assert db.get(ServidorFisico, host) is None
        assert (db.scalar(select(func.count(Hipervisor.id))) or 0) == 0
        assert (db.scalar(select(func.count(MaquinaVirtual.id))) or 0) == 0
    finally:
        db.close()


def test_editar_sin_csrf_rechazado(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-csrf", "funcion_unica")
    respuesta = client.post(f"/servidores/{fisico}/editar", data={
        "nombre": "srv-csrf", "tipo": "funcion_unica",
    })
    assert respuesta.status_code == 403
