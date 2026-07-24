"""Configuración del sistema en JSON (solo administradores).

Replica ``app/routes/configuracion.py`` para el frontend Next.js: consultar los
ajustes agrupados (con su valor efectivo y origen), guardar un lote de cambios,
restablecer una clave a su valor base y enviar un correo de prueba. Los secretos
(p. ej. la contraseña SMTP) nunca se devuelven en claro.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import ajustes, audit, notifications
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import Usuario

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("configuracion.gestionar"))
CSRF = Depends(verificar_csrf_json)


class CambiosInput(BaseModel):
    # Mapa clave→valor con los ajustes a modificar. Los secretos vacíos o
    # ausentes no se tocan. Acepta valores nativos (int/bool/str).
    cambios: dict[str, object] = {}


class RestablecerInput(BaseModel):
    clave: str = ""


class PruebaCorreoInput(BaseModel):
    destinatario: str = ""


@router.get("/configuracion")
def configuracion_ver(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    return {
        "grupos": ajustes.snapshot(db),
        "info_sistema": ajustes.info_sistema(),
    }


@router.put("/configuracion", dependencies=[CSRF])
def configuracion_guardar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: CambiosInput,
):
    try:
        modificadas = ajustes.guardar(db, cuerpo.cambios, usuario, request=request)
    except ajustes.ErrorAjuste as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"modificadas": modificadas}


@router.post("/configuracion/restablecer", dependencies=[CSRF])
def configuracion_restablecer(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: RestablecerInput,
):
    try:
        cambiado = ajustes.restablecer(db, cuerpo.clave, usuario, request=request)
    except ajustes.ErrorAjuste as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"restablecido": cambiado}


@router.post("/configuracion/probar-correo", dependencies=[CSRF])
def configuracion_probar_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: PruebaCorreoInput,
):
    try:
        enviados = notifications.enviar_prueba(cuerpo.destinatario)
    except notifications.ErrorCorreo as exc:
        audit.registrar(db, audit.CORREO_PRUEBA, request=request, usuario=usuario,
                        detalle=f"Prueba de correo fallida: {exc}", exito=False)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    audit.registrar(db, audit.CORREO_PRUEBA, request=request, usuario=usuario,
                    detalle=f"Correo de prueba enviado a {len(enviados)} destinatario(s).")
    return {"ok": True, "destinatarios": len(enviados)}
