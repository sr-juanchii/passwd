"""Inventario en JSON: dashboard, servidores, hipervisores y máquinas virtuales.

Replica las reglas de negocio y el control de acceso por objeto de
``app/routes/inventory.py`` (un host de virtualización aloja hipervisores; las
VMs viven en un hipervisor; el analista solo ve activos concedidos), devolviendo
JSON en lugar de plantillas.
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
    serializar_hipervisor_breve,
    serializar_hipervisor_detalle,
    serializar_servidor_detalle,
    serializar_servidor_nodo,
    serializar_vm_breve,
    serializar_vm_detalle,
)
from app.config import get_settings
from app.database import get_db
from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ESTADO_ACTIVO,
    ESTADOS_ACTIVO,
    ROL_ANALISTA,
    TIPO_FUNCION_UNICA,
    TIPO_HOST_VIRTUALIZACION,
    TIPOS_SERVIDOR,
    Credencial,
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
    tipo: str = TIPO_FUNCION_UNICA
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
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


class VmInput(BaseModel):
    nombre: str = ""
    sistema_operativo: str = ""
    ip: str = ""
    descripcion: str = ""
    estado: str = ESTADO_ACTIVO
    etiquetas: str = ""


def _estado_valido(estado: str) -> str:
    return estado if estado in ESTADOS_ACTIVO else ESTADO_ACTIVO


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
# Dashboard (árbol completo o concesiones del analista)
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
        .options(
            selectinload(ServidorFisico.hipervisores)
            .selectinload(Hipervisor.maquinas_virtuales)
            .selectinload(MaquinaVirtual.credenciales),
            selectinload(ServidorFisico.hipervisores).selectinload(Hipervisor.credenciales),
            selectinload(ServidorFisico.credenciales),
        )
        .order_by(ServidorFisico.nombre)
    ).all()
    limite_rotacion = ahora_utc() - timedelta(days=get_settings().rotation_max_days)
    resumen = {
        "servidores": len(servidores),
        "hipervisores": db.scalar(select(func.count(Hipervisor.id))) or 0,
        "vms": db.scalar(select(func.count(MaquinaVirtual.id))) or 0,
        "credenciales": db.scalar(select(func.count(Credencial.id))) or 0,
        "rotacion_vencida": db.scalar(
            select(func.count(Credencial.id)).where(Credencial.password_rotada_en < limite_rotacion)
        ) or 0,
    }
    return {
        "es_analista": False,
        "resumen": resumen,
        "arbol": [serializar_servidor_nodo(db, usuario, s) for s in servidores],
    }


# ---------------------------------------------------------------------------
# Servidores físicos
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
    datos["hipervisores"] = [serializar_hipervisor_breve(h) for h in servidor.hipervisores]
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
    if cuerpo.tipo not in TIPOS_SERVIDOR:
        raise HTTPException(status_code=400, detail="Tipo de servidor inválido.")
    if db.scalar(select(ServidorFisico).where(func.lower(ServidorFisico.nombre) == nombre.lower())):
        raise HTTPException(status_code=409, detail="Ya existe un servidor con ese nombre.")

    servidor = ServidorFisico(
        nombre=nombre, tipo=cuerpo.tipo, descripcion=cuerpo.descripcion.strip(),
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
                    objeto_tipo="servidor_fisico", objeto_id=servidor.id,
                    detalle=f"{nombre} ({cuerpo.tipo})")
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
    if cuerpo.tipo not in TIPOS_SERVIDOR:
        raise HTTPException(status_code=400, detail="Tipo de servidor inválido.")
    if cuerpo.tipo == TIPO_FUNCION_UNICA and servidor.hipervisores:
        raise HTTPException(status_code=400,
                            detail="No puede marcarse de función única: tiene hipervisores asociados.")
    if db.scalar(select(ServidorFisico).where(
            func.lower(ServidorFisico.nombre) == nombre.lower(), ServidorFisico.id != servidor.id)):
        raise HTTPException(status_code=409, detail="Ya existe otro servidor con ese nombre.")

    servidor.nombre = nombre
    servidor.tipo = cuerpo.tipo
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
    db.delete(servidor)  # cascada: hipervisores, VMs y credenciales
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor_id,
                    detalle=f"{nombre} (incluye hipervisores, VMs y credenciales en cascada)")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Hipervisores
# ---------------------------------------------------------------------------


def _validar_host(servidor: ServidorFisico) -> None:
    if servidor.tipo != TIPO_HOST_VIRTUALIZACION:
        raise HTTPException(status_code=400,
                            detail="Solo un servidor host de virtualización puede alojar hipervisores.")


@router.post("/servidores/{servidor_id}/hipervisores", dependencies=[CSRF])
def hipervisor_crear(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: HipervisorInput,
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    _validar_host(servidor)
    nombre = cuerpo.nombre.strip()
    if not nombre or not cuerpo.plataforma.strip():
        raise HTTPException(status_code=400, detail="Nombre y plataforma son obligatorios.")

    hipervisor = Hipervisor(
        servidor_fisico_id=servidor.id, nombre=nombre, plataforma=cuerpo.plataforma.strip(),
        version=cuerpo.version.strip(), ip_gestion=cuerpo.ip_gestion.strip(),
        descripcion=cuerpo.descripcion.strip(),
        estado=_estado_valido(cuerpo.estado), etiquetas=normalizar_etiquetas(cuerpo.etiquetas),
    )
    db.add(hipervisor)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor.id,
                    detalle=f"{nombre} ({cuerpo.plataforma.strip()}) en {servidor.nombre}")
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
    hipervisor.nombre = nombre
    hipervisor.plataforma = cuerpo.plataforma.strip()
    hipervisor.version = cuerpo.version.strip()
    hipervisor.ip_gestion = cuerpo.ip_gestion.strip()
    hipervisor.descripcion = cuerpo.descripcion.strip()
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
    servidor_id = hipervisor.servidor_fisico_id
    db.delete(hipervisor)
    audit.registrar(db, audit.ACTIVO_ELIMINADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor_id,
                    detalle=f"{nombre} (incluye VMs y credenciales en cascada)")
    return {"ok": True, "servidor_fisico_id": servidor_id}


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
