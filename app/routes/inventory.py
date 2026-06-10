"""Inventario relacional: servidores físicos, hipervisores y máquinas virtuales.

Reglas de negocio:
- Un servidor físico es de *función única* (un solo sistema) o *host de
  virtualización* (sin función única; aloja hipervisores).
- Solo los hosts de virtualización admiten hipervisores.
- Las máquinas virtuales viven siempre dentro de un hipervisor.
- No se permite degradar a función única un servidor con hipervisores.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import audit
from app.config import get_settings
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import (
    TIPO_FUNCION_UNICA,
    TIPO_HOST_VIRTUALIZACION,
    TIPOS_SERVIDOR,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
)

router = APIRouter()

VER = Depends(requiere_permiso("inventario.ver"))
GESTIONAR = Depends(requiere_permiso("inventario.gestionar"))


def _redir(url: str, msg: str) -> RedirectResponse:
    return RedirectResponse(f"{url}?msg={quote(msg)}", status_code=303)


def _obtener_o_404(db: Session, modelo, objeto_id: int):
    objeto = db.get(modelo, objeto_id)
    if objeto is None:
        raise HTTPException(status_code=404, detail="El recurso solicitado no existe.")
    return objeto


# ---------------------------------------------------------------------------
# Panel principal: árbol completo del inventario
# ---------------------------------------------------------------------------


@router.get("/")
def dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    msg: str = "",
):
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
    totales = {
        "fisicos": len(servidores),
        "hipervisores": db.scalar(select(func.count(Hipervisor.id))) or 0,
        "vms": db.scalar(select(func.count(MaquinaVirtual.id))) or 0,
        "credenciales": db.scalar(select(func.count(Credencial.id))) or 0,
        "rotacion_vencida": db.scalar(
            select(func.count(Credencial.id)).where(Credencial.password_rotada_en < limite_rotacion)
        ) or 0,
    }
    return render(request, "dashboard.html", {
        "usuario_actual": usuario, "servidores": servidores, "totales": totales, "msg": msg,
    })


# ---------------------------------------------------------------------------
# Servidores físicos
# ---------------------------------------------------------------------------


@router.get("/servidores/nuevo")
def servidor_nuevo_form(request: Request, usuario: Annotated[Usuario, GESTIONAR]):
    return render(request, "servidor_form.html",
                  {"usuario_actual": usuario, "servidor": None, "tipos": TIPOS_SERVIDOR})


@router.post("/servidores/nuevo", dependencies=[Depends(verificar_csrf)])
def servidor_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = TIPO_FUNCION_UNICA,
    descripcion: Annotated[str, Form()] = "",
    sistema_operativo: Annotated[str, Form()] = "",
    marca_modelo: Annotated[str, Form()] = "",
    ubicacion: Annotated[str, Form()] = "",
    ip_gestion: Annotated[str, Form()] = "",
):
    nombre = nombre.strip()
    error = ""
    if not nombre:
        error = "El nombre es obligatorio."
    elif tipo not in TIPOS_SERVIDOR:
        error = "Tipo de servidor inválido."
    elif db.scalar(select(ServidorFisico).where(func.lower(ServidorFisico.nombre) == nombre.lower())):
        error = "Ya existe un servidor con ese nombre."
    if error:
        return render(request, "servidor_form.html",
                      {"usuario_actual": usuario, "servidor": None, "tipos": TIPOS_SERVIDOR, "error": error},
                      status_code=400)

    servidor = ServidorFisico(
        nombre=nombre, tipo=tipo, descripcion=descripcion.strip(),
        sistema_operativo=sistema_operativo.strip(), marca_modelo=marca_modelo.strip(),
        ubicacion=ubicacion.strip(), ip_gestion=ip_gestion.strip(),
    )
    db.add(servidor)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor.id, detalle=f"{nombre} ({tipo})")
    return _redir(f"/servidores/{servidor.id}", "Servidor físico registrado.")


@router.get("/servidores/{servidor_id}")
def servidor_detalle(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    msg: str = "",
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    return render(request, "servidor_detalle.html",
                  {"usuario_actual": usuario, "servidor": servidor, "msg": msg})


@router.get("/servidores/{servidor_id}/editar")
def servidor_editar_form(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    return render(request, "servidor_form.html",
                  {"usuario_actual": usuario, "servidor": servidor, "tipos": TIPOS_SERVIDOR})


@router.post("/servidores/{servidor_id}/editar", dependencies=[Depends(verificar_csrf)])
def servidor_editar(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = TIPO_FUNCION_UNICA,
    descripcion: Annotated[str, Form()] = "",
    sistema_operativo: Annotated[str, Form()] = "",
    marca_modelo: Annotated[str, Form()] = "",
    ubicacion: Annotated[str, Form()] = "",
    ip_gestion: Annotated[str, Form()] = "",
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    nombre = nombre.strip()
    error = ""
    if not nombre:
        error = "El nombre es obligatorio."
    elif tipo not in TIPOS_SERVIDOR:
        error = "Tipo de servidor inválido."
    elif tipo == TIPO_FUNCION_UNICA and servidor.hipervisores:
        error = "No puede marcarse de función única: tiene hipervisores asociados."
    elif db.scalar(select(ServidorFisico).where(
            func.lower(ServidorFisico.nombre) == nombre.lower(), ServidorFisico.id != servidor.id)):
        error = "Ya existe otro servidor con ese nombre."
    if error:
        return render(request, "servidor_form.html",
                      {"usuario_actual": usuario, "servidor": servidor, "tipos": TIPOS_SERVIDOR, "error": error},
                      status_code=400)

    servidor.nombre = nombre
    servidor.tipo = tipo
    servidor.descripcion = descripcion.strip()
    servidor.sistema_operativo = sistema_operativo.strip()
    servidor.marca_modelo = marca_modelo.strip()
    servidor.ubicacion = ubicacion.strip()
    servidor.ip_gestion = ip_gestion.strip()
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="servidor_fisico", objeto_id=servidor.id, detalle=nombre)
    return _redir(f"/servidores/{servidor.id}", "Servidor actualizado.")


@router.post("/servidores/{servidor_id}/eliminar", dependencies=[Depends(verificar_csrf)])
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
    return _redir("/", f"Servidor «{nombre}» eliminado con todo su contenido.")


# ---------------------------------------------------------------------------
# Hipervisores
# ---------------------------------------------------------------------------


def _validar_host(servidor: ServidorFisico) -> None:
    if servidor.tipo != TIPO_HOST_VIRTUALIZACION:
        raise HTTPException(status_code=400,
                            detail="Solo un servidor host de virtualización puede alojar hipervisores.")


@router.get("/servidores/{servidor_id}/hipervisores/nuevo")
def hipervisor_nuevo_form(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    _validar_host(servidor)
    return render(request, "hipervisor_form.html",
                  {"usuario_actual": usuario, "servidor": servidor, "hipervisor": None})


@router.post("/servidores/{servidor_id}/hipervisores/nuevo", dependencies=[Depends(verificar_csrf)])
def hipervisor_crear(
    request: Request,
    servidor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    plataforma: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    ip_gestion: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    servidor = _obtener_o_404(db, ServidorFisico, servidor_id)
    _validar_host(servidor)
    nombre = nombre.strip()
    if not nombre or not plataforma.strip():
        return render(request, "hipervisor_form.html",
                      {"usuario_actual": usuario, "servidor": servidor, "hipervisor": None,
                       "error": "Nombre y plataforma son obligatorios."}, status_code=400)

    hipervisor = Hipervisor(
        servidor_fisico_id=servidor.id, nombre=nombre, plataforma=plataforma.strip(),
        version=version.strip(), ip_gestion=ip_gestion.strip(), descripcion=descripcion.strip(),
    )
    db.add(hipervisor)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor.id,
                    detalle=f"{nombre} ({plataforma}) en {servidor.nombre}")
    return _redir(f"/hipervisores/{hipervisor.id}", "Hipervisor registrado.")


@router.get("/hipervisores/{hipervisor_id}")
def hipervisor_detalle(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    msg: str = "",
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    return render(request, "hipervisor_detalle.html",
                  {"usuario_actual": usuario, "hipervisor": hipervisor, "msg": msg})


@router.get("/hipervisores/{hipervisor_id}/editar")
def hipervisor_editar_form(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    return render(request, "hipervisor_form.html",
                  {"usuario_actual": usuario, "servidor": hipervisor.servidor_fisico, "hipervisor": hipervisor})


@router.post("/hipervisores/{hipervisor_id}/editar", dependencies=[Depends(verificar_csrf)])
def hipervisor_editar(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    plataforma: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    ip_gestion: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    nombre = nombre.strip()
    if not nombre or not plataforma.strip():
        return render(request, "hipervisor_form.html",
                      {"usuario_actual": usuario, "servidor": hipervisor.servidor_fisico,
                       "hipervisor": hipervisor, "error": "Nombre y plataforma son obligatorios."},
                      status_code=400)
    hipervisor.nombre = nombre
    hipervisor.plataforma = plataforma.strip()
    hipervisor.version = version.strip()
    hipervisor.ip_gestion = ip_gestion.strip()
    hipervisor.descripcion = descripcion.strip()
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="hipervisor", objeto_id=hipervisor.id, detalle=nombre)
    return _redir(f"/hipervisores/{hipervisor.id}", "Hipervisor actualizado.")


@router.post("/hipervisores/{hipervisor_id}/eliminar", dependencies=[Depends(verificar_csrf)])
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
    return _redir(f"/servidores/{servidor_id}", f"Hipervisor «{nombre}» eliminado.")


# ---------------------------------------------------------------------------
# Máquinas virtuales
# ---------------------------------------------------------------------------


@router.get("/hipervisores/{hipervisor_id}/vms/nueva")
def vm_nueva_form(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    return render(request, "vm_form.html", {"usuario_actual": usuario, "hipervisor": hipervisor, "vm": None})


@router.post("/hipervisores/{hipervisor_id}/vms/nueva", dependencies=[Depends(verificar_csrf)])
def vm_crear(
    request: Request,
    hipervisor_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    sistema_operativo: Annotated[str, Form()] = "",
    ip: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    hipervisor = _obtener_o_404(db, Hipervisor, hipervisor_id)
    nombre = nombre.strip()
    if not nombre:
        return render(request, "vm_form.html",
                      {"usuario_actual": usuario, "hipervisor": hipervisor, "vm": None,
                       "error": "El nombre es obligatorio."}, status_code=400)
    vm = MaquinaVirtual(
        hipervisor_id=hipervisor.id, nombre=nombre,
        sistema_operativo=sistema_operativo.strip(), ip=ip.strip(), descripcion=descripcion.strip(),
    )
    db.add(vm)
    db.flush()
    audit.registrar(db, audit.ACTIVO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="maquina_virtual", objeto_id=vm.id,
                    detalle=f"{nombre} en hipervisor {hipervisor.nombre}")
    return _redir(f"/vms/{vm.id}", "Máquina virtual registrada.")


@router.get("/vms/{vm_id}")
def vm_detalle(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    msg: str = "",
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    return render(request, "vm_detalle.html", {"usuario_actual": usuario, "vm": vm, "msg": msg})


@router.get("/vms/{vm_id}/editar")
def vm_editar_form(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    return render(request, "vm_form.html", {"usuario_actual": usuario, "hipervisor": vm.hipervisor, "vm": vm})


@router.post("/vms/{vm_id}/editar", dependencies=[Depends(verificar_csrf)])
def vm_editar(
    request: Request,
    vm_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
    sistema_operativo: Annotated[str, Form()] = "",
    ip: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    vm = _obtener_o_404(db, MaquinaVirtual, vm_id)
    nombre = nombre.strip()
    if not nombre:
        return render(request, "vm_form.html",
                      {"usuario_actual": usuario, "hipervisor": vm.hipervisor, "vm": vm,
                       "error": "El nombre es obligatorio."}, status_code=400)
    vm.nombre = nombre
    vm.sistema_operativo = sistema_operativo.strip()
    vm.ip = ip.strip()
    vm.descripcion = descripcion.strip()
    audit.registrar(db, audit.ACTIVO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="maquina_virtual", objeto_id=vm.id, detalle=nombre)
    return _redir(f"/vms/{vm.id}", "Máquina virtual actualizada.")


@router.post("/vms/{vm_id}/eliminar", dependencies=[Depends(verificar_csrf)])
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
    return _redir(f"/hipervisores/{hipervisor_id}", f"Máquina virtual «{nombre}» eliminada.")
