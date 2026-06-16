"""Pruebas del inventario: servidores dedicados, hipervisores y máquinas virtuales."""

from __future__ import annotations

from sqlalchemy import func, select

from tests.conftest import autenticar_admin, csrf_de, sesion_bd


def _crear_servidor(client, nombre: str, tipo: str = "funcion_unica") -> int:
    """Crea un servidor dedicado. El parámetro `tipo` se conserva por
    compatibilidad con las llamadas existentes pero ya no se usa (el modelo
    nuevo no distingue tipos de servidor)."""
    csrf = csrf_de(client, "/servidores/nuevo")
    respuesta = client.post("/servidores/nuevo", data={
        "nombre": nombre, "descripcion": f"Descripción de {nombre}",
        "sistema_operativo": "Debian 12", "ubicacion": "Sala principal",
        "ip_gestion": "10.0.0.10", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303, f"No se creó el servidor: {respuesta.status_code}"
    return int(respuesta.headers["location"].split("?")[0].rsplit("/", 1)[-1])


def _crear_hipervisor(client, servidor_id: int | None, nombre: str) -> int:
    """Crea un hipervisor de nivel superior. `servidor_id` se ignora (compat)."""
    csrf = csrf_de(client, "/hipervisores/nuevo")
    respuesta = client.post("/hipervisores/nuevo", data={
        "nombre": nombre, "plataforma": "Proxmox VE", "version": "8.2",
        "ip_gestion": "10.0.0.11", "descripcion": "Nodo de virtualización",
        "ram": "128 GB", "cpu": "2x Xeon", "csrf_token": csrf,
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


def test_jerarquia_completa_y_panel(client):
    autenticar_admin(client)

    _crear_servidor(client, "srv-nomina")
    hipervisor = _crear_hipervisor(client, None, "pve-nodo-01")
    vm = _crear_vm(client, hipervisor, "vm-correo")

    panel = client.get("/")
    assert panel.status_code == 200
    for texto in ("srv-nomina", "pve-nodo-01", "vm-correo"):
        assert texto in panel.text, f"Falta «{texto}» en el panel"

    detalle_vm = client.get(f"/vms/{vm}")
    assert detalle_vm.status_code == 200
    assert "pve-nodo-01" in detalle_vm.text  # relación VM → hipervisor


def test_hipervisor_es_de_nivel_superior(client):
    """El hipervisor se crea directamente, sin servidor físico padre."""
    autenticar_admin(client)
    hipervisor = _crear_hipervisor(client, None, "pve-suelto")
    detalle = client.get(f"/hipervisores/{hipervisor}")
    assert detalle.status_code == 200
    assert "pve-suelto" in detalle.text


def test_nombre_de_servidor_duplicado_rechazado(client):
    autenticar_admin(client)
    _crear_servidor(client, "srv-repetido")

    csrf = csrf_de(client, "/servidores/nuevo")
    respuesta = client.post("/servidores/nuevo", data={
        "nombre": "SRV-REPETIDO", "csrf_token": csrf,
    })
    assert respuesta.status_code == 400
    assert "Ya existe" in respuesta.text


def test_nombre_de_hipervisor_duplicado_rechazado(client):
    autenticar_admin(client)
    _crear_hipervisor(client, None, "pve-repetido")

    csrf = csrf_de(client, "/hipervisores/nuevo")
    respuesta = client.post("/hipervisores/nuevo", data={
        "nombre": "PVE-REPETIDO", "plataforma": "ESXi", "csrf_token": csrf,
    })
    assert respuesta.status_code == 400
    assert "Ya existe" in respuesta.text


def test_eliminacion_en_cascada(client):
    autenticar_admin(client)
    hipervisor = _crear_hipervisor(client, None, "pve-cascada")
    _crear_vm(client, hipervisor, "vm-cascada")

    csrf = csrf_de(client, f"/hipervisores/{hipervisor}")
    respuesta = client.post(f"/hipervisores/{hipervisor}/eliminar", data={"csrf_token": csrf})
    assert respuesta.status_code == 303

    db = sesion_bd()
    try:
        from app.models import Hipervisor, MaquinaVirtual

        assert db.get(Hipervisor, hipervisor) is None
        assert (db.scalar(select(func.count(MaquinaVirtual.id))) or 0) == 0
    finally:
        db.close()


def test_editar_sin_csrf_rechazado(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-csrf")
    respuesta = client.post(f"/servidores/{fisico}/editar", data={"nombre": "srv-csrf"})
    assert respuesta.status_code == 403
