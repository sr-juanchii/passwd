"""Inventario en JSON: dashboard, servidores, hipervisores, VMs y dispositivos de red.

Modelo de tres activos de nivel superior: servidores dedicados (con sus
credenciales), hipervisores físicos (con hardware) que alojan directamente sus
máquinas virtuales, y dispositivos de red (switches, routers, firewalls…).
Replica el control de acceso por objeto de ``app/routes/inventory.py`` (el
analista solo ve activos concedidos).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import access, audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.api_web.serializers import (
    serializar_analista,
    serializar_concesion,
    serializar_credencial,
    serializar_dispositivo_detalle,
    serializar_dispositivo_nodo,
    serializar_hipervisor_detalle,
    serializar_hipervisor_nodo,
    serializar_servidor_detalle,
    serializar_servidor_nodo,
    serializar_vm_breve,
    serializar_vm_detalle,
)
from app.config import get_settings
from app.database import get_db
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ESTADO_ACTIVO,
    ESTADOS_ACTIVO,
    ROL_ANALISTA,
    TIPO_DISPOSITIVO_SWITCH,
    TIPOS_DISPOSITIVO,
    Credencial,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
    normalizar_etiquetas,
)
from app.rbac import tiene_permiso

router = APIRouter()

VER = Depends(requiere_permiso_json("inventario.ver"))
GESTIONAR = Depends(requiere_permiso_json("inventario.gestionar"))
CSRF = Depends(verificar_csrf_json)


class ServidorInput(BaseModel):
    nombre: str = ""
    descripcion: str = ""
    sistema_operativo: str = ""
    marca_modelo: str = ""
    ubicacion: str = ""
    ip_gestion: str = ""
    ram: str = ""
    cpu: str = ""
    almacenamiento: str = ""
    numero_serie: str = ""
    garantia_hasta: str = ""
    proveedor: str = ""
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


class HipervisorInput(BaseModel):
    nombre: str = ""
    plataforma: str = ""
    version: str = ""
    ip_gestion: str = ""
    descripcion: str = ""
    marca_modelo: str = ""
    ubicacion: str = ""
    ram: str = ""
    cpu: str = ""
    almacenamiento: str = ""
    numero_serie: str = ""
    garantia_hasta: str = ""
    proveedor: str = ""
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


class VmInput(BaseModel):
    nombre: str = ""
    sistema_operativo: str = ""
    ip: str = ""
    descripcion: str = ""
    ram: str = ""
    cpu: str = ""
    almacenamiento: str = ""
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


class DispositivoInput(BaseModel):
    nombre: str = ""
    tipo_dispositivo: str = TIPO_DISPOSITIVO_SWITCH
    marca_modelo: str = ""
    version: str = ""
    ip_gestion: str = ""
    ubicacion: str = ""
    puertos: str = ""
    descripcion: str = ""
    numero_serie: str = ""
    garantia_hasta: str = ""
    proveedor: str = ""
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


def _estado_valido(estado: str) -> str:
    return estado if estado in ESTADOS_ACTIVO else ESTADO_ACTIVO


def _tipo_dispositivo_valido(tipo: str) -> str:
    return tipo if tipo in TIPOS_DISPOSITIVO else TIPO_DISPOSITIVO_SWITCH


def _obtener_o_404(db: Session, modelo, objeto_id: int):
    objeto = db.get(modelo, objeto_id)
    if objeto is None:
        raise HTTPException(status_code=404, detail="El recurso solicitado no existe.")
    return objeto


def _exigir_ver_activo(request: Request, db: Session, usuario: Usuario, tipo: str, activo_id: int) -> None:
    """Control de acceso por objeto: 404 (sin filtrar existencia) si no procede."""
    if access.puede_ver_activo(db, usuario, tipo, activo_id):
        return
    audit.registrar(
        db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
        objeto_tipo=tipo, objeto_id=activo_id,
        detalle="Acceso a activo sin concesión vigente.", exito=False,
    )
    db.commit()
    raise HTTPException(status_code=404, detail="El recurso solicitado no existe.")


def _credenciales_ordenadas(db: Session, usuario: Usuario, credenciales) -> list[dict]:
    return [serializar_credencial(db, usuario, c) for c in credenciales]


def _accesos_admin(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> dict:
    """Datos de concesiones y analistas para quien gestiona accesos (admin)."""
    if not tiene_permiso(usuario.rol, "accesos.gestionar"):
        return {}
    concesiones = access.concesiones_de_activo(db, tipo, activo_id)
    return {
        "accesos": [serializar_concesion(c) for c in concesiones],
        "analistas": [serializar_analista(a) for a in access.analistas_activos(db)],
    }


# ---------------------------------------------------------------------------
# Dashboard (servidores dedicados + hipervisores, o concesiones del analista)
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    if usuario.rol == ROL_ANALISTA:
        concesiones = access.concesiones_vigentes_de_usuario(db, usuario.id)
        concesiones.sort(key=lambda c: (c.tipo_activo, c.nombre_activo.lower()))
        return {
            "es_analista": True,
            "concesiones": [serializar_concesion(c) for c in concesiones],
        }

    servidores = db.scalars(
        select(ServidorFisico)
        .options(selectinload(ServidorFisico.credenciales))
        .order_by(ServidorFisico.nombre)
    ).all()
    hipervisores = db.scalars(
        select(Hipervisor)
        .options(
            selectinload(Hipervisor.maquinas_virtuales).selectinload(MaquinaVirtual.credenciales),
            selectinload(Hipervisor.credenciales),
        )
        .order_by(Hipervisor.nombre)
    ).all()
    dispositivos = db.scalars(
        select(DispositivoRed)
        .options(selectinload(DispositivoRed.credenciales))
        .order_by(DispositivoRed.nombre)
    ).all()
    limite_rotacion = ahora_utc() - timedelta(days=get_settings().rotation_max_days)
    resumen = {
        "servidores": len(servidores),
        "hipervisores": len(hipervisores),
        "vms": db.scalar(select(func.count(MaquinaVirtual.id))) or 0,
        "dispositivos": len(dispositivos),
        "credenciales": db.scalar(select(func.count(Credencial.id))) or 0,
        "rotacion_vencida": db.scalar(
            select(func.count(Credencial.id)).where(Credencial.password_rotada_en < limite_rotacion)
        ) or 0,
    }
    return {
        "es_analista": False,
        "resumen": resumen,
        "servidores": [serializar_servidor_nodo(db, usuario, s) for s in servidores],
        "hipervisores": [serializar_hipervisor_nodo(db, usuario, h) for h in hipervisores],
        "dispositivos": [serializar_dispositivo_nodo(db, usuario, d) for d in dispositivos],
    }


# ---------------------------------------------------------------------------
# Servidores físicos dedicados
# ---------------------------------------------------------------------------


@router.get("/servidores/{servidor_id}")
def servidor_detalle(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    _exigir_ver_activo(request, db, usuario, ACTIVO_FISICO, servidor_id)
    datos = serializar_servidor_detalle(servidor)
    datos["credenciales"] = _credenciales_ordenadas(db, usuario, servidor.credenciales)
    datos["puede_gestionar"] = tiene_permiso(usuario.rol, "inventario.gestionar")
    datos["puede_gestionar_accesos"] = tiene_permiso(usuario.rol, "accesos.gestionar")
    datos["tiene_notas"] = servidor.notas_cifradas is not None
    datos.update(_accesos_admin(db, usuario, ACTIVO_FISICO, servidor_id))
    return datos


@router.post("/servidores", dependencies=[CSRF])
def servidor_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: ServidorInput,
):
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    if db.scalar(select(ServidorFisico).where(func.lower(ServidorFisico.nombre) == nombre.lower())):
        raise HTTPException(status_code=409, detail="Ya existe un servidor con ese nombre.")

    servidor = ServidorFisico(
        nombre=nombre, descripcion=cuerpo.descripcion.strip(),
        sistema_operativo=cuerpo.sistema_operativo.strip(), marca_modelo=cuerpo.marca_modelo.strip(),
        ubicacion=cuerpo.ubicacion.strip(), ip_gestion=cuerpo.ip_gestion.strip(),
        ram=cuerpo.ram.strip(), cpu=cuerpo.cpu.strip(), almacenamiento=cuerpo.almacenamiento.strip(),
        numero_serie=cuerpo.numero_serie.strip(), garantia_hasta=cuerpo.garantia_hasta.strip(),
        proveedor=cuerpo.proveedor.strip(), estado=_estado_valido(cuerpo.estado),
        etiquetas=normalizar_etiquetas(cuerpo.etiquetas),
    )
    db.add(servidor)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor.id, detalle=nombre)
    return {"id": servidor.id}


@router.put("/servidores/{servidor_id}", dependencies=[CSRF])
def servidor_editar(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: ServidorInput,
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    if db.scalar(select(ServidorFisico).where(
            func.lower(ServidorFisico.nombre) == nombre.lower(), ServidorFisico.id != servidor.id)):
        raise HTTPException(status_code=409, detail="Ya existe otro servidor con ese nombre.")

    servidor.nombre = nombre
    servidor.descripcion = cuerpo.descripcion.strip()
    servidor.sistema_operativo = cuerpo.sistema_operativo.strip()
    servidor.marca_modelo = cuerpo.marca_modelo.strip()
    servidor.ubicacion = cuerpo.ubicacion.strip()
    servidor.ip_gestion = cuerpo.ip_gestion.strip()
    servidor.ram = cuerpo.ram.strip()
    servidor.cpu = cuerpo.cpu.strip()
    servidor.almacenamiento = cuerpo.almacenamiento.strip()
    servidor.numero_serie = cuerpo.numero_serie.strip()
    servidor.garantia_hasta = cuerpo.garantia_hasta.strip()
    servidor.proveedor = cuerpo.proveedor.strip()
    servidor.estado = _estado_valido(cuerpo.estado)
    servidor.etiquetas = normalizar_etiquetas(cuerpo.etiquetas)
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor.id, detalle=nombre)
    return {"id": servidor.id}


@router.delete("/servidores/{servidor_id}", dependencies=[CSRF])
def servidor_eliminar(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    nombre = servidor.nombre
    db.delete(servidor)  # cascada: credenciales del servidor
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor_id,
                    detalle=f"{nombre} (incluye credenciales en cascada)")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Hipervisores (activos de nivel superior con hardware)
# ---------------------------------------------------------------------------


@router.post("/hipervisores", dependencies=[CSRF])
def hipervisor_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: HipervisorInput,
):
    nombre = cuerpo.nombre.strip()
    if not nombre or not cuerpo.plataforma.strip():
        raise HTTPException(status_code=400, detail="Nombre y plataforma son obligatorios.")
    if db.scalar(select(Hipervisor).where(func.lower(Hipervisor.nombre) == nombre.lower())):
        raise HTTPException(status_code=409, detail="Ya existe un hipervisor con ese nombre.")

    hipervisor = Hipervisor(
        nombre=nombre, plataforma=cuerpo.plataforma.strip(), version=cuerpo.version.strip(),
        ip_gestion=cuerpo.ip_gestion.strip(), descripcion=cuerpo.descripcion.strip(),
        marca_modelo=cuerpo.marca_modelo.strip(), ubicacion=cuerpo.ubicacion.strip(),
        ram=cuerpo.ram.strip(), cpu=cuerpo.cpu.strip(), almacenamiento=cuerpo.almacenamiento.strip(),
        numero_serie=cuerpo.numero_serie.strip(), garantia_hasta=cuerpo.garantia_hasta.strip(),
        proveedor=cuerpo.proveedor.strip(), estado=_estado_valido(cuerpo.estado),
        etiquetas=normalizar_etiquetas(cuerpo.etiquetas),
    )
    db.add(hipervisor)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor.id,
                    detalle=f"{nombre} ({cuerpo.plataforma.strip()})")
    return {"id": hipervisor.id}


@router.get("/hipervisores/{hipervisor_id}")
def hipervisor_detalle(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    _exigir_ver_activo(request, db, usuario, ACTIVO_HIPERVISOR, hipervisor_id)
    datos = serializar_hipervisor_detalle(hipervisor)
    datos["credenciales"] = _credenciales_ordenadas(db, usuario, hipervisor.credenciales)
    datos["vms"] = [serializar_vm_breve(v) for v in hipervisor.maquinas_virtuales]
    datos["puede_gestionar"] = tiene_permiso(usuario.rol, "inventario.gestionar")
    datos["puede_gestionar_accesos"] = tiene_permiso(usuario.rol, "accesos.gestionar")
    datos["tiene_notas"] = hipervisor.notas_cifradas is not None
    datos.update(_accesos_admin(db, usuario, ACTIVO_HIPERVISOR, hipervisor_id))
    return datos


@router.put("/hipervisores/{hipervisor_id}", dependencies=[CSRF])
def hipervisor_editar(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: HipervisorInput,
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    nombre = cuerpo.nombre.strip()
    if not nombre or not cuerpo.plataforma.strip():
        raise HTTPException(status_code=400, detail="Nombre y plataforma son obligatorios.")
    if db.scalar(select(Hipervisor).where(
            func.lower(Hipervisor.nombre) == nombre.lower(), Hipervisor.id != hipervisor.id)):
        raise HTTPException(status_code=409, detail="Ya existe otro hipervisor con ese nombre.")
    hipervisor.nombre = nombre
    hipervisor.plataforma = cuerpo.plataforma.strip()
    hipervisor.version = cuerpo.version.strip()
    hipervisor.ip_gestion = cuerpo.ip_gestion.strip()
    hipervisor.descripcion = cuerpo.descripcion.strip()
    hipervisor.marca_modelo = cuerpo.marca_modelo.strip()
    hipervisor.ubicacion = cuerpo.ubicacion.strip()
    hipervisor.ram = cuerpo.ram.strip()
    hipervisor.cpu = cuerpo.cpu.strip()
    hipervisor.almacenamiento = cuerpo.almacenamiento.strip()
    hipervisor.numero_serie = cuerpo.numero_serie.strip()
    hipervisor.garantia_hasta = cuerpo.garantia_hasta.strip()
    hipervisor.proveedor = cuerpo.proveedor.strip()
    hipervisor.estado = _estado_valido(cuerpo.estado)
    hipervisor.etiquetas = normalizar_etiquetas(cuerpo.etiquetas)
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor.id, detalle=nombre)
    return {"id": hipervisor.id}


@router.delete("/hipervisores/{hipervisor_id}", dependencies=[CSRF])
def hipervisor_eliminar(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    nombre = hipervisor.nombre
    db.delete(hipervisor)
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor_id,
                    detalle=f"{nombre} (incluye VMs y credenciales en cascada)")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Máquinas virtuales
# ---------------------------------------------------------------------------


@router.post("/hipervisores/{hipervisor_id}/vms", dependencies=[CSRF])
def vm_crear(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: VmInput,
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    vm = MaquinaVirtual(
        hipervisor_id=hipervisor.id, nombre=nombre,
        sistema_operativo=cuerpo.sistema_operativo.strip(), ip=cuerpo.ip.strip(),
        descripcion=cuerpo.descripcion.strip(),
        ram=cuerpo.ram.strip(), cpu=cuerpo.cpu.strip(), almacenamiento=cuerpo.almacenamiento.strip(),
        estado=_estado_valido(cuerpo.estado), etiquetas=normalizar_etiquetas(cuerpo.etiquetas),
    )
    db.add(vm)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="maquina_virtual", objeto_id=vm.id,
                    detalle=f"{nombre} en hipervisor {hipervisor.nombre}")
    return {"id": vm.id}


@router.get("/vms/{vm_id}")
def vm_detalle(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    _exigir_ver_activo(request, db, usuario, ACTIVO_VM, vm_id)
    datos = serializar_vm_detalle(vm)
    datos["credenciales"] = _credenciales_ordenadas(db, usuario, vm.credenciales)
    datos["puede_gestionar"] = tiene_permiso(usuario.rol, "inventario.gestionar")
    datos["puede_gestionar_accesos"] = tiene_permiso(usuario.rol, "accesos.gestionar")
    datos["tiene_notas"] = vm.notas_cifradas is not None
    datos.update(_accesos_admin(db, usuario, ACTIVO_VM, vm_id))
    return datos


@router.put("/vms/{vm_id}", dependencies=[CSRF])
def vm_editar(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: VmInput,
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    vm.nombre = nombre
    vm.sistema_operativo = cuerpo.sistema_operativo.strip()
    vm.ip = cuerpo.ip.strip()
    vm.descripcion = cuerpo.descripcion.strip()
    vm.ram = cuerpo.ram.strip()
    vm.cpu = cuerpo.cpu.strip()
    vm.almacenamiento = cuerpo.almacenamiento.strip()
    vm.estado = _estado_valido(cuerpo.estado)
    vm.etiquetas = normalizar_etiquetas(cuerpo.etiquetas)
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="maquina_virtual", objeto_id=vm.id, detalle=nombre)
    return {"id": vm.id}


@router.delete("/vms/{vm_id}", dependencies=[CSRF])
def vm_eliminar(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    nombre = vm.nombre
    hipervisor_id = vm.hipervisor_id
    db.delete(vm)
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="maquina_virtual", objeto_id=vm_id, detalle=nombre)
    return {"ok": True, "hipervisor_id": hipervisor_id}


# ---------------------------------------------------------------------------
# Dispositivos de red (switches, routers, firewalls…)
# ---------------------------------------------------------------------------


@router.get("/dispositivos/{dispositivo_id}")
def dispositivo_detalle(
    request: Request,
    dispositivo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    dispositivo = _obtener_o_404(db, DispositivoRed, dispositivo_id)
    _exigir_ver_activo(request, db, usuario, ACTIVO_DISPOSITIVO, dispositivo_id)
    datos = serializar_dispositivo_detalle(dispositivo)
    datos["credenciales"] = _credenciales_ordenadas(db, usuario, dispositivo.credenciales)
    datos["puede_gestionar"] = tiene_permiso(usuario.rol, "inventario.gestionar")
    datos["puede_gestionar_accesos"] = tiene_permiso(usuario.rol, "accesos.gestionar")
    datos["tiene_notas"] = dispositivo.notas_cifradas is not None
    datos.update(_accesos_admin(db, usuario, ACTIVO_DISPOSITIVO, dispositivo_id))
    return datos


@router.post("/dispositivos", dependencies=[CSRF])
def dispositivo_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: DispositivoInput,
):
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    if db.scalar(select(DispositivoRed).where(func.lower(DispositivoRed.nombre) == nombre.lower())):
        raise HTTPException(status_code=409, detail="Ya existe un dispositivo con ese nombre.")

    dispositivo = DispositivoRed(
        nombre=nombre, tipo_dispositivo=_tipo_dispositivo_valido(cuerpo.tipo_dispositivo),
        marca_modelo=cuerpo.marca_modelo.strip(), version=cuerpo.version.strip(),
        ip_gestion=cuerpo.ip_gestion.strip(), ubicacion=cuerpo.ubicacion.strip(),
        puertos=cuerpo.puertos.strip(), descripcion=cuerpo.descripcion.strip(),
        numero_serie=cuerpo.numero_serie.strip(), garantia_hasta=cuerpo.garantia_hasta.strip(),
        proveedor=cuerpo.proveedor.strip(), estado=_estado_valido(cuerpo.estado),
        etiquetas=normalizar_etiquetas(cuerpo.etiquetas),
    )
    db.add(dispositivo)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="dispositivo_red", objeto_id=dispositivo.id,
                    detalle=f"{nombre} ({dispositivo.tipo_dispositivo})")
    return {"id": dispositivo.id}


@router.put("/dispositivos/{dispositivo_id}", dependencies=[CSRF])
def dispositivo_editar(
    request: Request,
    dispositivo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: DispositivoInput,
):
    dispositivo = _obtener_o_404(db, DispositivoRed, dispositivo_id)
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    if db.scalar(select(DispositivoRed).where(
            func.lower(DispositivoRed.nombre) == nombre.lower(), DispositivoRed.id != dispositivo.id)):
        raise HTTPException(status_code=409, detail="Ya existe otro dispositivo con ese nombre.")

    dispositivo.nombre = nombre
    dispositivo.tipo_dispositivo = _tipo_dispositivo_valido(cuerpo.tipo_dispositivo)
    dispositivo.marca_modelo = cuerpo.marca_modelo.strip()
    dispositivo.version = cuerpo.version.strip()
    dispositivo.ip_gestion = cuerpo.ip_gestion.strip()
    dispositivo.ubicacion = cuerpo.ubicacion.strip()
    dispositivo.puertos = cuerpo.puertos.strip()
    dispositivo.descripcion = cuerpo.descripcion.strip()
    dispositivo.numero_serie = cuerpo.numero_serie.strip()
    dispositivo.garantia_hasta = cuerpo.garantia_hasta.strip()
    dispositivo.proveedor = cuerpo.proveedor.strip()
    dispositivo.estado = _estado_valido(cuerpo.estado)
    dispositivo.etiquetas = normalizar_etiquetas(cuerpo.etiquetas)
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="dispositivo_red", objeto_id=dispositivo.id, detalle=nombre)
    return {"id": dispositivo.id}


@router.delete("/dispositivos/{dispositivo_id}", dependencies=[CSRF])
def dispositivo_eliminar(
    request: Request,
    dispositivo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    dispositivo = _obtener_o_404(db, DispositivoRed, dispositivo_id)
    nombre = dispositivo.nombre
    db.delete(dispositivo)  # cascada: credenciales del dispositivo
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="dispositivo_red", objeto_id=dispositivo_id,
                    detalle=f"{nombre} (incluye credenciales en cascada)")
    return {"ok": True}
