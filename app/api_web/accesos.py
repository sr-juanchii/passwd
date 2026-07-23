"""Concesiones de acceso por activo en JSON (solo administradores).

Replica ``app/routes/accesos.py``: upsert de concesiones (usuario, activo, nivel,
caducidad) y revocación, ambas auditadas.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    NIVEL_VER,
    NIVELES_CONCESION,
    ROL_ANALISTA,
    ConcesionAcceso,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
)

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("accesos.gestionar"))
CSRF = Depends(verificar_csrf_json)

# tipo de activo → (modelo, columna FK en ConcesionAcceso)
_ACTIVOS = {
    ACTIVO_FISICO: (ServidorFisico, "servidor_fisico_id"),
    ACTIVO_HIPERVISOR: (Hipervisor, "hipervisor_id"),
    ACTIVO_VM: (MaquinaVirtual, "maquina_virtual_id"),
    ACTIVO_DISPOSITIVO: (DispositivoRed, "dispositivo_red_id"),
}


class ConcederInput(BaseModel):
    usuario_id: int = 0
    tipo: str = ""
    activo_id: int = 0
    nivel: str = NIVEL_VER
    expira_dias: int | None = None


def _resolver_activo(db: Session, tipo: str, activo_id: int):
    if tipo not in _ACTIVOS:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    modelo, columna = _ACTIVOS[tipo]
    instancia = db.get(modelo, activo_id)
    if instancia is None:
        raise HTTPException(status_code=404, detail="El activo indicado no existe.")
    return instancia, columna


@router.post("/accesos/conceder", dependencies=[CSRF])
def conceder(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Usuario, GESTIONAR],
    cuerpo: ConcederInput,
):
    instancia, columna = _resolver_activo(db, cuerpo.tipo, cuerpo.activo_id)

    objetivo = db.get(Usuario, cuerpo.usuario_id)
    if objetivo is None or objetivo.rol != ROL_ANALISTA or not objetivo.activo:
        raise HTTPException(status_code=400, detail="El destinatario debe ser un analista activo.")
    if cuerpo.nivel not in NIVELES_CONCESION:
        raise HTTPException(status_code=400, detail="Nivel de acceso inválido.")

    expira_en = None
    if cuerpo.expira_dias is not None:
        if cuerpo.expira_dias <= 0:
            raise HTTPException(status_code=400, detail="La caducidad debe ser un número de días positivo.")
        expira_en = ahora_utc() + timedelta(days=cuerpo.expira_dias)

    # Upsert: si ya hay una concesión para (usuario, activo), se actualiza.
    existente = db.scalar(
        select(ConcesionAcceso).where(
            ConcesionAcceso.usuario_id == cuerpo.usuario_id,
            getattr(ConcesionAcceso, columna) == cuerpo.activo_id,
        )
    )
    if existente is not None:
        existente.nivel = cuerpo.nivel
        existente.expira_en = expira_en
        existente.concedido_por_id = admin.id
        accion_detalle = "actualizada"
    else:
        db.add(ConcesionAcceso(
            usuario_id=cuerpo.usuario_id, nivel=cuerpo.nivel, expira_en=expira_en,
            concedido_por_id=admin.id,
            **{columna: cuerpo.activo_id},
        ))
        accion_detalle = "creada"

    caduca = f"; caduca {expira_en:%d/%m/%Y}" if expira_en else "; sin caducidad"
    audit.registrar(db, audit.ACCESO_CONCEDIDO, request=request, usuario=admin,
                    objeto_tipo=cuerpo.tipo, objeto_id=cuerpo.activo_id,
                    detalle=f"Concesión {accion_detalle} a {objetivo.username} sobre "
                            f"{instancia.nombre} (nivel {cuerpo.nivel}{caduca})")
    return {"ok": True}


@router.post("/accesos/{concesion_id}/revocar", dependencies=[CSRF])
def revocar(
    request: Request,
    concesion_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Usuario, GESTIONAR],
):
    concesion = db.get(ConcesionAcceso, concesion_id)
    if concesion is None:
        raise HTTPException(status_code=404, detail="La concesión no existe.")
    # Capturamos todo ANTES de borrar (después la fila queda inaccesible).
    tipo = concesion.tipo_activo
    activo_id = (
        concesion.servidor_fisico_id
        or concesion.hipervisor_id
        or concesion.maquina_virtual_id
        or concesion.dispositivo_red_id
    )
    detalle = (f"Acceso de {concesion.usuario.username} sobre {concesion.nombre_activo} "
               f"(nivel {concesion.nivel}) revocado")
    db.delete(concesion)
    audit.registrar(db, audit.ACCESO_REVOCADO, request=request, usuario=admin,
                    objeto_tipo=tipo, objeto_id=activo_id, detalle=detalle)
    return {"ok": True}
