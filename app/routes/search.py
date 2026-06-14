"""Búsqueda global en el inventario (todos los roles autenticados).

Busca servidores, hipervisores, VMs y credenciales (por usuario/servicio, nunca
por contraseña). Los resultados se filtran por el control de acceso por objeto:
un analista solo ve coincidencias en los activos que tiene concedidos, de modo
que la búsqueda no se convierte en una vía de enumeración (OWASP API1/BOLA).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import access
from app.database import get_db
from app.deps import render, requiere_permiso
from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
)

router = APIRouter()

VER = Depends(requiere_permiso("inventario.ver"))
LONGITUD_MINIMA = 2
LIMITE_POR_TIPO = 50


def _like(columna, patron):
    return func.lower(columna).like(patron)


@router.get("/buscar")
def buscar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    q: str = "",
):
    consulta = q.strip()
    contexto: dict = {"usuario_actual": usuario, "q": consulta}
    if len(consulta) < LONGITUD_MINIMA:
        contexto["aviso"] = f"Escriba al menos {LONGITUD_MINIMA} caracteres."
        return render(request, "buscar.html", contexto)

    patron = f"%{consulta.lower()}%"

    fisicos = db.scalars(
        select(ServidorFisico).where(or_(
            _like(ServidorFisico.nombre, patron),
            _like(ServidorFisico.ip_gestion, patron),
            _like(ServidorFisico.ubicacion, patron),
            _like(ServidorFisico.sistema_operativo, patron),
            _like(ServidorFisico.etiquetas, patron),
        )).order_by(ServidorFisico.nombre).limit(LIMITE_POR_TIPO)
    ).all()
    hipervisores = db.scalars(
        select(Hipervisor).where(or_(
            _like(Hipervisor.nombre, patron),
            _like(Hipervisor.plataforma, patron),
            _like(Hipervisor.ip_gestion, patron),
            _like(Hipervisor.etiquetas, patron),
        )).order_by(Hipervisor.nombre).limit(LIMITE_POR_TIPO)
    ).all()
    vms = db.scalars(
        select(MaquinaVirtual).where(or_(
            _like(MaquinaVirtual.nombre, patron),
            _like(MaquinaVirtual.ip, patron),
            _like(MaquinaVirtual.sistema_operativo, patron),
            _like(MaquinaVirtual.etiquetas, patron),
        )).order_by(MaquinaVirtual.nombre).limit(LIMITE_POR_TIPO)
    ).all()
    credenciales = db.scalars(
        select(Credencial).where(or_(
            _like(Credencial.usuario_acceso, patron),
            _like(Credencial.servicio, patron),
        )).limit(LIMITE_POR_TIPO)
    ).all()

    # Filtrado por acceso a nivel de objeto (clave para no filtrar el inventario).
    def visibles(items, tipo):
        return [it for it in items if access.puede_ver_activo(db, usuario, tipo, it.id)]

    contexto["fisicos"] = visibles(fisicos, ACTIVO_FISICO)
    contexto["hipervisores"] = visibles(hipervisores, ACTIVO_HIPERVISOR)
    contexto["vms"] = visibles(vms, ACTIVO_VM)
    contexto["credenciales"] = [c for c in credenciales if access.puede_ver_credencial(db, usuario, c)]
    contexto["total"] = (
        len(contexto["fisicos"]) + len(contexto["hipervisores"])
        + len(contexto["vms"]) + len(contexto["credenciales"])
    )
    return render(request, "buscar.html", contexto)
