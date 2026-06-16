"""Consulta y exportación de la bitácora de auditoría en JSON (admin y auditor).

Replica ``app/routes/audit_view.py``, incluida la misma mitigación de inyección
de fórmulas en la exportación CSV.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app import audit as audit_log
from app.api_web.deps import requiere_permiso_json
from app.api_web.serializers import serializar_registro
from app.database import get_db
from app.models import RegistroAuditoria, Usuario, ahora_utc

router = APIRouter()

VER = Depends(requiere_permiso_json("auditoria.ver"))
POR_PAGINA = 50

# Columnas de la exportación (en orden). La bitácora nunca contiene secretos.
_COLUMNAS_CSV = [
    "fecha_utc", "usuario", "accion", "objeto_tipo", "objeto_id",
    "detalle", "direccion_ip", "agente_usuario", "exito",
]


def _consulta_filtrada(filtro_usuario: str, filtro_accion: str) -> Select:
    consulta = select(RegistroAuditoria).order_by(
        RegistroAuditoria.fecha.desc(), RegistroAuditoria.id.desc()
    )
    if filtro_usuario.strip():
        patron = f"%{filtro_usuario.strip().lower()}%"
        consulta = consulta.where(func.lower(RegistroAuditoria.username).like(patron))
    if filtro_accion.strip():
        consulta = consulta.where(RegistroAuditoria.accion == filtro_accion.strip())
    return consulta


def _celda_segura(valor) -> str:
    """Mitiga la inyección de fórmulas en CSV (Excel/Sheets): antepone una
    comilla simple a las celdas que empiezan por un carácter activo."""
    texto = "" if valor is None else str(valor)
    if texto and texto[0] in ("=", "+", "-", "@", "\t", "\r"):
        texto = "'" + texto
    return texto


@router.get("/auditoria")
def auditoria(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    filtro_usuario: str = "",
    filtro_accion: str = "",
    pagina: int = 1,
):
    pagina = max(pagina, 1)
    consulta = _consulta_filtrada(filtro_usuario, filtro_accion)
    conteo = select(func.count()).select_from(consulta.subquery())

    total = db.scalar(conteo) or 0
    registros = db.scalars(consulta.offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA)).all()
    acciones = db.scalars(
        select(RegistroAuditoria.accion).distinct().order_by(RegistroAuditoria.accion)
    ).all()

    return {
        "registros": [serializar_registro(r) for r in registros],
        "pagina": pagina,
        "total_paginas": max((total + POR_PAGINA - 1) // POR_PAGINA, 1),
        "acciones": list(acciones),
        "filtro_usuario": filtro_usuario,
        "filtro_accion": filtro_accion,
    }


@router.get("/auditoria/export.csv")
def auditoria_export(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    filtro_usuario: str = "",
    filtro_accion: str = "",
):
    """Exporta a CSV el conjunto filtrado completo (evidencia de cumplimiento)."""
    registros = db.scalars(_consulta_filtrada(filtro_usuario, filtro_accion)).all()

    # La exportación es una operación sensible (egreso masivo): queda auditada.
    audit_log.registrar(
        db, audit_log.AUDITORIA_EXPORTADA, request=request, usuario=usuario,
        detalle=f"{len(registros)} registro(s); filtros usuario='{filtro_usuario}' accion='{filtro_accion}'",
    )
    db.commit()

    def generar():
        buffer = io.StringIO()
        escritor = csv.writer(buffer)
        escritor.writerow(_COLUMNAS_CSV)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for r in registros:
            escritor.writerow([
                r.fecha.isoformat(),
                _celda_segura(r.username),
                _celda_segura(r.accion),
                _celda_segura(r.objeto_tipo),
                _celda_segura(r.objeto_id),
                _celda_segura(r.detalle),
                _celda_segura(r.direccion_ip),
                _celda_segura(r.agente_usuario),
                "si" if r.exito else "no",
            ])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    nombre = f"auditoria-{ahora_utc():%Y%m%d-%H%M%S}.csv"
    return StreamingResponse(
        generar(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )
