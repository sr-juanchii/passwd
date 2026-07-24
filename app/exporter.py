"""Export en claro del inventario para MIGRACIÓN entre versiones.

Genera un CSV con **todas** las credenciales del inventario y su contraseña en
claro, junto con los activos (servidor/hipervisor/VM), en el **mismo formato que
acepta el importador** (``app/api_web/importer.py``): así el archivo es fácil de
editar y volver a importar (round-trip). NO incluye los vaults personales (son
privados de cada usuario) ni la auditoría.

⚠️ El archivo contiene secretos en claro: quien lo genere debe custodiarlo y
destruirlo tras la migración. El acceso está restringido por RBAC
(``inventario.exportar``), auditado y servido con ``Cache-Control: no-store``.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    Credencial,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
)
from app.security.crypto import descifrar

# Cabecera canónica: unión de todas las columnas que entiende el importador.
# El mismo orden se usa para la plantilla descargable.
COLUMNAS = [
    "tipo", "nombre", "padre", "activo_tipo",
    "plataforma", "version", "sistema_operativo", "ip",
    "tipo_dispositivo", "puertos",
    "descripcion", "estado", "etiquetas", "restringido",
    "marca_modelo", "ubicacion", "ram", "cpu", "almacenamiento",
    "numero_serie", "garantia_hasta", "proveedor",
    "usuario_acceso", "password", "servicio", "puerto",
]


def _si_no(valor: bool) -> str:
    return "si" if valor else ""

# El importador espera activo_tipo "servidor" para los físicos; el modelo usa
# "fisico" en su property tipo_activo.
_ACTIVO_TIPO_CSV = {
    ACTIVO_FISICO: "servidor",
    ACTIVO_HIPERVISOR: "hipervisor",
    ACTIVO_DISPOSITIVO: "dispositivo",
}


def _fila() -> dict[str, str]:
    return dict.fromkeys(COLUMNAS, "")


def _serializar_a_filas(db: Session, incluir_restringidos: bool = True) -> list[dict[str, str]]:
    """Filas del inventario. Si ``incluir_restringidos`` es False, se omiten los
    activos restringidos a administradores (y las VMs de hipervisores
    restringidos) junto con sus credenciales: es lo que ve un operador."""
    filas: list[dict[str, str]] = []

    consulta_s = select(ServidorFisico).order_by(ServidorFisico.nombre)
    consulta_h = select(Hipervisor).order_by(Hipervisor.nombre)
    consulta_d = select(DispositivoRed).order_by(DispositivoRed.nombre)
    if not incluir_restringidos:
        consulta_s = consulta_s.where(ServidorFisico.restringido.is_(False))
        consulta_h = consulta_h.where(Hipervisor.restringido.is_(False))
        consulta_d = consulta_d.where(DispositivoRed.restringido.is_(False))

    for s in db.scalars(consulta_s).all():
        f = _fila()
        f.update(tipo="servidor", nombre=s.nombre, sistema_operativo=s.sistema_operativo,
                 ip=s.ip_gestion, descripcion=s.descripcion, estado=s.estado, etiquetas=s.etiquetas,
                 restringido=_si_no(s.restringido),
                 marca_modelo=s.marca_modelo, ubicacion=s.ubicacion, ram=s.ram, cpu=s.cpu,
                 almacenamiento=s.almacenamiento, numero_serie=s.numero_serie,
                 garantia_hasta=s.garantia_hasta, proveedor=s.proveedor)
        filas.append(f)

    hipervisores = db.scalars(consulta_h).all()
    hipervisores_visibles = {h.id for h in hipervisores}
    for h in hipervisores:
        f = _fila()
        f.update(tipo="hipervisor", nombre=h.nombre, plataforma=h.plataforma, version=h.version,
                 ip=h.ip_gestion, descripcion=h.descripcion, estado=h.estado, etiquetas=h.etiquetas,
                 restringido=_si_no(h.restringido),
                 marca_modelo=h.marca_modelo, ubicacion=h.ubicacion, ram=h.ram, cpu=h.cpu,
                 almacenamiento=h.almacenamiento, numero_serie=h.numero_serie,
                 garantia_hasta=h.garantia_hasta, proveedor=h.proveedor)
        filas.append(f)

    vms = db.scalars(
        select(MaquinaVirtual).options(selectinload(MaquinaVirtual.hipervisor))
        .order_by(MaquinaVirtual.nombre)
    ).all()
    for v in vms:
        # La VM hereda la restricción del hipervisor: si su hipervisor no es
        # visible, la VM tampoco (evita filtrar su existencia por el CSV).
        if not incluir_restringidos and v.hipervisor_id not in hipervisores_visibles:
            continue
        f = _fila()
        f.update(tipo="vm", nombre=v.nombre, padre=v.hipervisor.nombre if v.hipervisor else "",
                 sistema_operativo=v.sistema_operativo, ip=v.ip, descripcion=v.descripcion,
                 estado=v.estado, etiquetas=v.etiquetas,
                 ram=v.ram, cpu=v.cpu, almacenamiento=v.almacenamiento)
        filas.append(f)

    for d in db.scalars(consulta_d).all():
        f = _fila()
        f.update(tipo="dispositivo", nombre=d.nombre, tipo_dispositivo=d.tipo_dispositivo,
                 version=d.version, ip=d.ip_gestion, puertos=d.puertos,
                 descripcion=d.descripcion, estado=d.estado, etiquetas=d.etiquetas,
                 restringido=_si_no(d.restringido),
                 marca_modelo=d.marca_modelo, ubicacion=d.ubicacion,
                 numero_serie=d.numero_serie, garantia_hasta=d.garantia_hasta,
                 proveedor=d.proveedor)
        filas.append(f)

    credenciales = db.scalars(
        select(Credencial).options(
            selectinload(Credencial.servidor_fisico),
            selectinload(Credencial.hipervisor),
            selectinload(Credencial.maquina_virtual),
            selectinload(Credencial.dispositivo_red),
        )
    ).all()
    for c in credenciales:
        if not incluir_restringidos and _credencial_restringida(c, hipervisores_visibles):
            continue
        f = _fila()
        f.update(tipo="credencial",
                 activo_tipo=_ACTIVO_TIPO_CSV.get(c.tipo_activo, c.tipo_activo),
                 padre=c.nombre_activo, usuario_acceso=c.usuario_acceso,
                 password=descifrar(c.password_cifrada), servicio=c.servicio,
                 puerto="" if c.puerto is None else str(c.puerto), descripcion=c.descripcion)
        filas.append(f)

    return filas


def _credencial_restringida(c: Credencial, hipervisores_visibles: set[int]) -> bool:
    """¿La credencial cuelga de un activo no visible para el operador?"""
    if c.servidor_fisico is not None:
        return c.servidor_fisico.restringido
    if c.hipervisor is not None:
        return c.hipervisor.restringido
    if c.dispositivo_red is not None:
        return c.dispositivo_red.restringido
    if c.maquina_virtual is not None:
        return c.maquina_virtual.hipervisor_id not in hipervisores_visibles
    return False


def _a_csv(filas: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=COLUMNAS, extrasaction="ignore")
    escritor.writeheader()
    escritor.writerows(filas)
    return buffer.getvalue()


def exportar_csv(db: Session, incluir_restringidos: bool = True) -> str:
    """CSV en claro del inventario, listo para editar y re-importar.

    ``incluir_restringidos=False`` omite los activos restringidos a
    administradores (lo que corresponde a un operador que exporta)."""
    return _a_csv(_serializar_a_filas(db, incluir_restringidos))


def plantilla_csv() -> str:
    """CSV de ejemplo (cabecera + una fila por tipo) para arrancar una importación."""
    ejemplos = [
        {"tipo": "servidor", "nombre": "srv-bd", "sistema_operativo": "Debian 12",
         "ip": "10.0.0.5", "descripcion": "BD de nómina", "estado": "activo",
         "etiquetas": "producción,crítico", "ram": "64 GB", "cpu": "2x Xeon Silver",
         "almacenamiento": "2x 960 GB SSD"},
        {"tipo": "hipervisor", "nombre": "pve-01", "plataforma": "Proxmox VE", "version": "8.2",
         "ip": "10.0.0.7", "descripcion": "Nodo de virtualización", "estado": "activo",
         "ram": "256 GB", "cpu": "2x EPYC 7402", "almacenamiento": "4x 1.92 TB NVMe"},
        {"tipo": "vm", "nombre": "vm-correo", "padre": "pve-01", "sistema_operativo": "Ubuntu 24.04",
         "ip": "10.0.1.10", "descripcion": "Correo", "estado": "activo", "etiquetas": "correo",
         "ram": "8 GB", "cpu": "4 vCPU", "almacenamiento": "120 GB"},
        {"tipo": "dispositivo", "nombre": "sw-core-01", "tipo_dispositivo": "switch",
         "marca_modelo": "Cisco Catalyst 9300", "version": "IOS-XE 17.9",
         "ip": "10.0.0.2", "ubicacion": "Rack A1", "puertos": "48x 1GbE + 4x SFP+",
         "descripcion": "Switch de núcleo", "estado": "activo", "etiquetas": "red,crítico"},
        {"tipo": "credencial", "activo_tipo": "servidor", "padre": "srv-bd",
         "usuario_acceso": "root", "password": "S3cret!", "servicio": "SSH", "puerto": "22",
         "descripcion": "Acceso root"},
        {"tipo": "credencial", "activo_tipo": "dispositivo", "padre": "sw-core-01",
         "usuario_acceso": "admin", "password": "S3cret!", "servicio": "SSH", "puerto": "22",
         "descripcion": "Gestión del switch"},
    ]
    filas = [{**_fila(), **e} for e in ejemplos]
    return _a_csv(filas)
