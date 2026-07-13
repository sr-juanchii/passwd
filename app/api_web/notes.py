"""Notas seguras cifradas por activo en JSON.

Replica ``app/routes/notes.py``: editar requiere gestionar inventario; revelar
requiere permiso de credenciales y el nivel adecuado de concesión, siempre
auditado y bajo el límite anti-exfiltración. El contenido en claro solo se
entrega en ``/revelar``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import access, audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.config import get_settings
from app.database import get_db
from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ROL_ANALISTA,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
)
from app.security import ratelimit
from app.security.crypto import cifrar, descifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("inventario.gestionar"))
REVELAR = Depends(requiere_permiso_json("credenciales.revelar"))
CSRF = Depends(verificar_csrf_json)

_ACTIVOS = {
    ACTIVO_FISICO: ServidorFisico,
    ACTIVO_HIPERVISOR: Hipervisor,
    ACTIVO_VM: MaquinaVirtual,
}


class NotasInput(BaseModel):
    contenido: str = ""


def _resolver(db: Session, tipo: str, activo_id: int):
    if tipo not in _ACTIVOS:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    activo = db.get(_ACTIVOS[tipo], activo_id)
    if activo is None:
        raise HTTPException(status_code=404, detail="El activo no existe.")
    return activo


@router.get("/activos/{tipo}/{activo_id}/notas")
def notas_estado(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    activo = _resolver(db, tipo, activo_id)
    return {"tiene_notas": activo.notas_cifradas is not None}


@router.put("/activos/{tipo}/{activo_id}/notas", dependencies=[CSRF])
def notas_guardar(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: NotasInput,
):
    activo = _resolver(db, tipo, activo_id)
    activo.notas_cifradas = cifrar(cuerpo.contenido) if cuerpo.contenido.strip() else None
    audit.registrar(db, audit.NOTA_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo=tipo, objeto_id=activo_id,
                    detalle=f"Notas {'actualizadas' if cuerpo.contenido.strip() else 'borradas'} "
                            f"en {activo.nombre}")
    return {"ok": True}


@router.post("/activos/{tipo}/{activo_id}/notas/revelar", dependencies=[CSRF])
def notas_revelar(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    activo = _resolver(db, tipo, activo_id)

    # Mismo control por objeto que las credenciales: el analista necesita el
    # nivel 'ver_credenciales' sobre el activo.
    if not access.puede_ver_activo(db, usuario, tipo, activo_id):
        raise HTTPException(status_code=404, detail="El activo no existe.")
    if not access.puede_revelar_en_activo(db, usuario, tipo, activo_id):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo=tipo, objeto_id=activo_id,
                        detalle="Sin nivel para revelar notas.", exito=False)
        db.commit()
        raise HTTPException(status_code=403, detail="No tiene permiso para ver estas notas.")

    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"revelar:{usuario.id}", limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes, db=db,
    ):
        audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                        objeto_tipo=tipo, objeto_id=activo_id, detalle="Notas.", exito=False)
        db.commit()
        raise HTTPException(status_code=429, detail="Límite de accesos alcanzado; espere unos minutos.")

    via = " (vía concesión)" if usuario.rol == ROL_ANALISTA else ""
    audit.registrar(db, audit.NOTA_REVELADA, request=request, usuario=usuario,
                    objeto_tipo=tipo, objeto_id=activo_id, detalle=f"{activo.nombre}{via}")
    contenido = descifrar(activo.notas_cifradas) if activo.notas_cifradas else ""
    return JSONResponse({"notas": contenido}, headers={"Cache-Control": "no-store"})
