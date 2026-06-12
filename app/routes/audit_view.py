"""Consulta de la bitácora de auditoría (roles admin y auditor)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import render, requiere_permiso
from app.models import RegistroAuditoria, Usuario

router = APIRouter()

POR_PAGINA = 50


@router.get("/auditoria")
def auditoria(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, Depends(requiere_permiso("auditoria.ver"))],
    filtro_usuario: str = "",
    filtro_accion: str = "",
    pagina: int = 1,
):
    pagina = max(pagina, 1)
    consulta = select(RegistroAuditoria).order_by(RegistroAuditoria.fecha.desc(), RegistroAuditoria.id.desc())
    conteo = select(func.count(RegistroAuditoria.id))
    if filtro_usuario.strip():
        patron = f"%{filtro_usuario.strip().lower()}%"
        consulta = consulta.where(func.lower(RegistroAuditoria.username).like(patron))
        conteo = conteo.where(func.lower(RegistroAuditoria.username).like(patron))
    if filtro_accion.strip():
        consulta = consulta.where(RegistroAuditoria.accion == filtro_accion.strip())
        conteo = conteo.where(RegistroAuditoria.accion == filtro_accion.strip())

    total = db.scalar(conteo) or 0
    registros = db.scalars(consulta.offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA)).all()
    acciones = db.scalars(
        select(RegistroAuditoria.accion).distinct().order_by(RegistroAuditoria.accion)
    ).all()

    return render(request, "auditoria.html", {
        "usuario_actual": usuario,
        "registros": registros,
        "acciones": acciones,
        "filtro_usuario": filtro_usuario,
        "filtro_accion": filtro_accion,
        "pagina": pagina,
        "total": total,
        "total_paginas": max((total + POR_PAGINA - 1) // POR_PAGINA, 1),
    })
