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
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    Credencial,
    DispositivoRed,
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

    # Restricción por acceso a nivel de objeto ANTES del LIMIT: si se
    # truncara primero, un analista podría no ver coincidencias de activos
    # que sí tiene concedidos más allá de las primeras filas.
    ids_fisicos = access.ids_activos_concedidos(db, usuario, ACTIVO_FISICO)
    ids_hipervisores = access.ids_activos_concedidos(db, usuario, ACTIVO_HIPERVISOR)
    ids_vms = access.ids_activos_concedidos(db, usuario, ACTIVO_VM)
    ids_dispositivos = access.ids_activos_concedidos(db, usuario, ACTIVO_DISPOSITIVO)

    consulta_fisicos = select(ServidorFisico).where(or_(
        _like(ServidorFisico.nombre, patron),
        _like(ServidorFisico.ip_gestion, patron),
        _like(ServidorFisico.ubicacion, patron),
        _like(ServidorFisico.sistema_operativo, patron),
        _like(ServidorFisico.etiquetas, patron),
    ))
    if ids_fisicos is not None:
        consulta_fisicos = consulta_fisicos.where(ServidorFisico.id.in_(ids_fisicos))
    fisicos = db.scalars(
        consulta_fisicos.order_by(ServidorFisico.nombre).limit(LIMITE_POR_TIPO)
    ).all()

    consulta_hipervisores = select(Hipervisor).where(or_(
        _like(Hipervisor.nombre, patron),
        _like(Hipervisor.plataforma, patron),
        _like(Hipervisor.ip_gestion, patron),
        _like(Hipervisor.etiquetas, patron),
    ))
    if ids_hipervisores is not None:
        consulta_hipervisores = consulta_hipervisores.where(Hipervisor.id.in_(ids_hipervisores))
    hipervisores = db.scalars(
        consulta_hipervisores.order_by(Hipervisor.nombre).limit(LIMITE_POR_TIPO)
    ).all()

    consulta_vms = select(MaquinaVirtual).where(or_(
        _like(MaquinaVirtual.nombre, patron),
        _like(MaquinaVirtual.ip, patron),
        _like(MaquinaVirtual.sistema_operativo, patron),
        _like(MaquinaVirtual.etiquetas, patron),
    ))
    if ids_vms is not None:
        consulta_vms = consulta_vms.where(MaquinaVirtual.id.in_(ids_vms))
    vms = db.scalars(
        consulta_vms.order_by(MaquinaVirtual.nombre).limit(LIMITE_POR_TIPO)
    ).all()

    consulta_dispositivos = select(DispositivoRed).where(or_(
        _like(DispositivoRed.nombre, patron),
        _like(DispositivoRed.tipo_dispositivo, patron),
        _like(DispositivoRed.marca_modelo, patron),
        _like(DispositivoRed.ip_gestion, patron),
        _like(DispositivoRed.ubicacion, patron),
        _like(DispositivoRed.etiquetas, patron),
    ))
    if ids_dispositivos is not None:
        consulta_dispositivos = consulta_dispositivos.where(DispositivoRed.id.in_(ids_dispositivos))
    dispositivos = db.scalars(
        consulta_dispositivos.order_by(DispositivoRed.nombre).limit(LIMITE_POR_TIPO)
    ).all()

    consulta_credenciales = select(Credencial).where(or_(
        _like(Credencial.usuario_acceso, patron),
        _like(Credencial.servicio, patron),
    ))
    # Cada tipo se filtra por su lista de visibles; ``None`` = ese tipo no se
    # filtra (todas sus credenciales entran). Así el prefiltro sirve tanto al
    # analista (cuatro listas) como al operador/auditor (mezcla None/lista
    # cuando hay activos restringidos).
    ids_por_columna = (
        (Credencial.servidor_fisico_id, ids_fisicos),
        (Credencial.hipervisor_id, ids_hipervisores),
        (Credencial.maquina_virtual_id, ids_vms),
        (Credencial.dispositivo_red_id, ids_dispositivos),
    )
    if any(ids is not None for _, ids in ids_por_columna):
        consulta_credenciales = consulta_credenciales.where(or_(*[
            columna.in_(ids) if ids is not None else columna.is_not(None)
            for columna, ids in ids_por_columna
        ]))
    credenciales = db.scalars(consulta_credenciales.limit(LIMITE_POR_TIPO)).all()

    # Filtrado por acceso a nivel de objeto (clave para no filtrar el inventario).
    def visibles(items, tipo):
        return [it for it in items if access.puede_ver_activo(db, usuario, tipo, it.id)]

    contexto["fisicos"] = visibles(fisicos, ACTIVO_FISICO)
    contexto["hipervisores"] = visibles(hipervisores, ACTIVO_HIPERVISOR)
    contexto["vms"] = visibles(vms, ACTIVO_VM)
    contexto["dispositivos"] = visibles(dispositivos, ACTIVO_DISPOSITIVO)
    contexto["credenciales"] = [c for c in credenciales if access.puede_ver_credencial(db, usuario, c)]
    contexto["total"] = (
        len(contexto["fisicos"]) + len(contexto["hipervisores"])
        + len(contexto["vms"]) + len(contexto["dispositivos"]) + len(contexto["credenciales"])
    )
    return render(request, "buscar.html", contexto)
