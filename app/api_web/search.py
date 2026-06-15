"""Búsqueda global en JSON (todos los roles autenticados).

Filtra los resultados por el control de acceso por objeto, igual que
``app/routes/search.py``: un analista solo ve coincidencias en los activos que
tiene concedidos. Nunca busca ni devuelve contraseñas.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import access
from app.api_web.deps import requiere_permiso_json
from app.api_web.serializers import (
    serializar_credencial,
    serializar_hipervisor_breve,
    serializar_vm_breve,
)
from app.database import get_db
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

VER = Depends(requiere_permiso_json("inventario.ver"))
LONGITUD_MINIMA = 2
LIMITE_POR_TIPO = 50


def _like(columna, patron):
    return func.lower(columna).like(patron)


def _servidor_breve(servidor: ServidorFisico) -> dict:
    return {
        "id": servidor.id,
        "nombre": servidor.nombre,
        "tipo": servidor.tipo,
        "etiqueta_tipo": servidor.etiqueta_tipo,
        "estado": servidor.estado,
        "ip_gestion": servidor.ip_gestion,
    }


@router.get("/buscar")
def buscar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    q: str = "",
):
    consulta = q.strip()
    if len(consulta) < LONGITUD_MINIMA:
        return {"q": consulta, "servidores": [], "hipervisores": [], "vms": [], "credenciales": []}

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

    return {
        "q": consulta,
        "servidores": [_servidor_breve(s) for s in visibles(fisicos, ACTIVO_FISICO)],
        "hipervisores": [serializar_hipervisor_breve(h) for h in visibles(hipervisores, ACTIVO_HIPERVISOR)],
        "vms": [serializar_vm_breve(v) for v in visibles(vms, ACTIVO_VM)],
        "credenciales": [
            serializar_credencial(db, usuario, c)
            for c in credenciales
            if access.puede_ver_credencial(db, usuario, c)
        ],
    }
