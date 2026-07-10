"""Pruebas de las features de preproducción:

- Especificaciones de VM (RAM/CPU/almacenamiento) en web y JSON.
- Vault personal por usuario (JSON y web): CRUD, aislamiento por dueño,
  revelado auditado y limitado, inclusión en el respaldo cifrado.
- Export en claro para migración (CSV round-trip con el importador) y plantilla.
- Alineación de la plantilla/importador con las specs de VM.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# VM specs (RAM / CPU / almacenamiento)
# ---------------------------------------------------------------------------


def test_vm_guarda_specs_web_y_json(client):
    autenticar_admin(client)
    hv = _crear_hipervisor(client, None, "pve-specs")

    csrf = csrf_de(client, f"/hipervisores/{hv}/vms/nueva")
    r = client.post(f"/hipervisores/{hv}/vms/nueva", data={
        "nombre": "vm-specs", "sistema_operativo": "Ubuntu 24.04", "ip": "10.0.0.30",
        "descripcion": "app", "ram": "8 GB", "cpu": "4 vCPU", "almacenamiento": "120 GB SSD",
        "estado": "activo", "etiquetas": "", "csrf_token": csrf,
    })
    assert r.status_code == 303
    vm_id = int(r.headers["location"].split("?")[0].rsplit("/", 1)[-1])

    db = sesion_bd()
    try:
        from app.models import MaquinaVirtual

        vm = db.get(MaquinaVirtual, vm_id)
        assert (vm.ram, vm.cpu, vm.almacenamiento) == ("8 GB", "4 vCPU", "120 GB SSD")
    finally:
        db.close()

    # Detalle web muestra las specs
    detalle = client.get(f"/vms/{vm_id}")
    assert "8 GB" in detalle.text and "4 vCPU" in detalle.text and "120 GB SSD" in detalle.text

    # La API JSON las expone y las edita
    datos = client.get(f"/api/web/vms/{vm_id}").json()
    assert datos["ram"] == "8 GB" and datos["cpu"] == "4 vCPU" and datos["almacenamiento"] == "120 GB SSD"

    csrf_json = client.get("/api/web/session").json()["csrf_token"]
    r = client.put(f"/api/web/vms/{vm_id}", headers={"X-CSRF-Token": csrf_json}, json={
        "nombre": "vm-specs", "sistema_operativo": "Ubuntu 24.04", "ip": "10.0.0.30",
        "descripcion": "app", "ram": "16 GB", "cpu": "8 vCPU", "almacenamiento": "240 GB",
        "estado": "activo", "etiquetas": "",
    })
    assert r.status_code == 200
    assert client.get(f"/api/web/vms/{vm_id}").json()["ram"] == "16 GB"


# ---------------------------------------------------------------------------
# Vault personal (JSON)
# ---------------------------------------------------------------------------


def _csrf_json(client) -> str:
    return client.get("/api/web/session").json()["csrf_token"]


def _crear_entrada(client, titulo="Correo personal", password="Mi-Clave-Personal-2026!"):
    csrf = _csrf_json(client)
    r = client.post("/api/web/vault", headers={"X-CSRF-Token": csrf}, json={
        "titulo": titulo, "usuario_acceso": "yo@correo.com", "password": password,
        "url": "https://correo.example", "categoria": "cuenta", "notas": "cuenta principal",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_vault_crud_y_revelado_json(client):
    autenticar_admin(client)
    eid = _crear_entrada(client)

    # Listado no expone la contraseña
    lista = client.get("/api/web/vault").json()["entradas"]
    assert len(lista) == 1 and lista[0]["titulo"] == "Correo personal"
    assert "password" not in lista[0]

    # Revelar entrega la contraseña (auditado, no-store)
    csrf = _csrf_json(client)
    rev = client.post(f"/api/web/vault/{eid}/revelar", headers={"X-CSRF-Token": csrf})
    assert rev.status_code == 200
    assert rev.json()["password"] == "Mi-Clave-Personal-2026!"
    assert rev.headers["cache-control"] == "no-store"

    # Editar sin contraseña la conserva
    r = client.put(f"/api/web/vault/{eid}", headers={"X-CSRF-Token": csrf}, json={
        "titulo": "Correo del trabajo", "usuario_acceso": "yo@empresa.com", "password": "",
        "url": "", "categoria": "servicio", "notas": "",
    })
    assert r.status_code == 200
    assert client.post(f"/api/web/vault/{eid}/revelar",
                       headers={"X-CSRF-Token": _csrf_json(client)}).json()["password"] == "Mi-Clave-Personal-2026!"

    # Eliminar
    assert client.delete(f"/api/web/vault/{eid}",
                         headers={"X-CSRF-Token": _csrf_json(client)}).status_code == 200
    assert client.get("/api/web/vault").json()["entradas"] == []


def test_vault_es_privado_del_dueno(client, crear_cliente):
    """Ni otro usuario ni el admin ven/revelan la entrada de alguien más."""
    autenticar_admin(client)
    clave = crear_usuario(client, "operador1", "operador")
    op = crear_cliente()
    autenticar_usuario_nuevo(op, "operador1", clave)

    eid = _crear_entrada(op, titulo="Secreto del operador")

    # El admin no ve la entrada del operador (404, sin filtrar existencia)
    assert client.get(f"/api/web/vault/{eid}").status_code == 404
    assert client.post(f"/api/web/vault/{eid}/revelar",
                       headers={"X-CSRF-Token": _csrf_json(client)}).status_code == 404
    # El admin tiene su propio vault, vacío
    assert client.get("/api/web/vault").json()["entradas"] == []
    # El operador sí ve la suya
    assert len(op.get("/api/web/vault").json()["entradas"]) == 1


def test_vault_revelado_auditado_y_limitado(client, monkeypatch):
    from app.config import get_settings
    from app.security import ratelimit

    autenticar_admin(client)
    eid = _crear_entrada(client)

    # Presupuesto anti-exfiltración del vault compartido en BD, reducido a 1.
    monkeypatch.setattr(get_settings(), "reveal_rate_limit", 1)
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "bd")

    assert client.post(f"/api/web/vault/{eid}/revelar",
                       headers={"X-CSRF-Token": _csrf_json(client)}).status_code == 200
    ratelimit.reiniciar()  # el conteo debe sobrevivir en BD, no en memoria
    assert client.post(f"/api/web/vault/{eid}/revelar",
                       headers={"X-CSRF-Token": _csrf_json(client)}).status_code == 429

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "vault_entrada_revelada")) is not None
    finally:
        db.close()


def test_vault_disponible_para_todos_los_roles(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "audi-vault", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "audi-vault", clave)
    # Un auditor (solo lectura del inventario) SÍ tiene su vault personal
    eid = _crear_entrada(aud, titulo="Cosa del auditor")
    assert aud.get(f"/api/web/vault/{eid}").status_code == 200


# ---------------------------------------------------------------------------
# Vault en el respaldo cifrado
# ---------------------------------------------------------------------------


def test_vault_se_incluye_en_respaldo_y_restauracion(client):
    from app import backup

    autenticar_admin(client)
    _crear_entrada(client, titulo="Para respaldo", password="Respaldo-Vault-2026!")

    db = sesion_bd()
    try:
        datos = backup.exportar(db, "FraseDeRespaldo-Segura-2026!")
        resumen = backup.restaurar(db, datos, "FraseDeRespaldo-Segura-2026!", sobrescribir=True)
        db.commit()
        assert resumen["vaults"] == 1
    finally:
        db.close()

    db = sesion_bd()
    try:
        from app.models import EntradaVault
        from app.security.crypto import descifrar

        entrada = db.scalar(select(EntradaVault))
        assert entrada.titulo == "Para respaldo"
        assert descifrar(entrada.password_cifrada) == "Respaldo-Vault-2026!"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Export en claro y round-trip con el importador
# ---------------------------------------------------------------------------


def _inventario_de_ejemplo(client):
    srv = _crear_servidor(client, "srv-export")
    _crear_credencial(client, "fisico", srv, "root")
    hv = _crear_hipervisor(client, None, "pve-export")
    vm = _crear_vm(client, hv, "vm-export")
    # Añadir specs a la VM por edición web
    csrf = csrf_de(client, f"/vms/{vm}/editar")
    client.post(f"/vms/{vm}/editar", data={
        "nombre": "vm-export", "sistema_operativo": "Ubuntu", "ip": "10.0.0.40",
        "descripcion": "", "ram": "8 GB", "cpu": "4 vCPU", "almacenamiento": "120 GB",
        "estado": "activo", "etiquetas": "", "csrf_token": csrf,
    })
    return srv, hv, vm


def test_export_en_claro_admin_contenido_y_auditoria(client):
    autenticar_admin(client)
    _inventario_de_ejemplo(client)

    csrf = csrf_de(client, "/importar")
    r = client.post("/exportar", data={"csrf_token": csrf})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "attachment" in r.headers["content-disposition"]
    cuerpo = r.text
    assert CLAVE_SECRETA in cuerpo          # la contraseña va en claro (migración)
    assert "vm-export" in cuerpo and "8 GB" in cuerpo and "4 vCPU" in cuerpo
    assert "srv-export" in cuerpo and "pve-export" in cuerpo

    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "inventario_exportado")) is not None
    finally:
        db.close()


def test_export_requiere_permiso(client, crear_cliente):
    autenticar_admin(client)
    clave = crear_usuario(client, "audi-exp", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "audi-exp", clave)
    # El auditor no tiene inventario.exportar
    assert aud.post("/exportar", data={"csrf_token": csrf_de(aud, "/")}).status_code == 403


def test_export_import_round_trip(client):
    """Exportar → vaciar inventario → importar el CSV reconstruye todo."""
    autenticar_admin(client)
    _inventario_de_ejemplo(client)

    r = client.post("/exportar", data={"csrf_token": csrf_de(client, "/importar")})
    csv_exportado = r.text

    # Vaciar el inventario (conservando usuarios/auditoría)
    db = sesion_bd()
    try:
        from app.models import Credencial, Hipervisor, MaquinaVirtual, ServidorFisico

        for modelo in (Credencial, MaquinaVirtual, Hipervisor, ServidorFisico):
            for fila in db.scalars(select(modelo)).all():
                db.delete(fila)
        db.commit()
        assert db.scalar(select(func.count(Credencial.id))) == 0
    finally:
        db.close()

    # Reimportar el CSV exportado
    csrf = csrf_de(client, "/importar")
    imp = client.post("/importar", data={"csrf_token": csrf},
                      files={"archivo": ("inv.csv", csv_exportado.encode("utf-8"), "text/csv")})
    assert imp.status_code == 200

    db = sesion_bd()
    try:
        from app.models import Credencial, Hipervisor, MaquinaVirtual, ServidorFisico
        from app.security.crypto import descifrar

        assert db.scalar(select(ServidorFisico).where(ServidorFisico.nombre == "srv-export")) is not None
        assert db.scalar(select(Hipervisor).where(Hipervisor.nombre == "pve-export")) is not None
        vm = db.scalar(select(MaquinaVirtual).where(MaquinaVirtual.nombre == "vm-export"))
        assert vm is not None and vm.ram == "8 GB" and vm.cpu == "4 vCPU"  # specs sobrevivieron
        cred = db.scalar(select(Credencial))
        assert descifrar(cred.password_cifrada) == CLAVE_SECRETA  # round-trip de la contraseña
    finally:
        db.close()


def test_vault_web_jinja_flujo_completo(client):
    """Paridad de la interfaz web: crear, listar y revelar en /vault."""
    autenticar_admin(client)
    csrf = csrf_de(client, "/vault/nueva")
    r = client.post("/vault/nueva", data={
        "titulo": "Cuenta web", "usuario_acceso": "yo@web.com",
        "password": "Clave-Web-Vault-2026!", "url": "https://web.example",
        "categoria": "cuenta", "notas": "", "csrf_token": csrf,
    })
    assert r.status_code == 303
    lista = client.get("/vault")
    assert lista.status_code == 200 and "Cuenta web" in lista.text

    db = sesion_bd()
    try:
        from app.models import EntradaVault

        eid = db.scalar(select(EntradaVault.id))
    finally:
        db.close()

    rev = client.post(f"/vault/{eid}/revelar", data={"csrf_token": csrf_de(client, "/vault")})
    assert rev.status_code == 200 and rev.json()["password"] == "Clave-Web-Vault-2026!"


def test_plantilla_csv_descargable(client):
    autenticar_admin(client)
    r = client.get("/plantilla.csv")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    # Cabecera con specs de VM incluidas
    primera_linea = r.text.splitlines()[0]
    for col in ("tipo", "ram", "cpu", "almacenamiento", "password"):
        assert col in primera_linea
