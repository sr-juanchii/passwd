"""Gestión de credenciales en JSON: CRUD, revelado, copiado e historial.

Este módulo **solo traduce HTTP ↔ servicio**. Las reglas —control de acceso por
objeto, límite anti-exfiltración, auditoría y la exigencia de una rotación
autorizada para cambiar una contraseña— viven en
``app/servicios/credenciales.py``, compartidas con la interfaz clásica.

Los listados nunca incluyen la contraseña; solo los endpoints de
revelado/copiado la entregan, con cabecera ``Cache-Control: no-store``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import Usuario
from app.servicios import credenciales as servicio
from app.servicios.credenciales import ErrorCredencial

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("credenciales.gestionar"))
REVELAR = Depends(requiere_permiso_json("credenciales.revelar"))
CSRF = Depends(verificar_csrf_json)

SIN_CACHE = {"Cache-Control": "no-store"}


class CredencialCrear(BaseModel):
    activo: str = ""
    activo_id: int = 0
    usuario_acceso: str = ""
    password: str = ""
    servicio: str = "SSH"
    puerto: int | None = None
    descripcion: str = ""
    usada_por: str = ""


class CredencialEditar(BaseModel):
    usuario_acceso: str = ""
    # "" = conservar la actual. Cambiarla exige una rotación ya autorizada:
    # ver app/servicios/rotacion.py.
    password: str = ""
    servicio: str = "SSH"
    puerto: int | None = None
    descripcion: str = ""
    usada_por: str = ""


def _error(exc: ErrorCredencial) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


def _sesion_id(request: Request) -> int | None:
    sesion = getattr(request.state, "sesion", None)
    return sesion.id if sesion is not None else None


@router.post("/credenciales", dependencies=[CSRF])
def credencial_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: CredencialCrear,
):
    try:
        credencial = servicio.crear(
            db, usuario=usuario, tipo_activo=cuerpo.activo, activo_id=cuerpo.activo_id,
            usuario_acceso=cuerpo.usuario_acceso, password=cuerpo.password,
            servicio=cuerpo.servicio, puerto=cuerpo.puerto, descripcion=cuerpo.descripcion,
            usada_por=cuerpo.usada_por, request=request,
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return {"id": credencial.id}


@router.get("/credenciales/{credencial_id}")
def credencial_editar_datos(
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    try:
        return servicio.detalle_para_editar(db, usuario, credencial_id)
    except ErrorCredencial as exc:
        raise _error(exc) from exc


@router.put("/credenciales/{credencial_id}", dependencies=[CSRF])
def credencial_editar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: CredencialEditar,
):
    try:
        credencial, _rotacion = servicio.actualizar(
            db, usuario=usuario, credencial_id=credencial_id,
            usuario_acceso=cuerpo.usuario_acceso, password=cuerpo.password,
            servicio=cuerpo.servicio, puerto=cuerpo.puerto, descripcion=cuerpo.descripcion,
            usada_por=cuerpo.usada_por, request=request,
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return {"id": credencial.id}


@router.delete("/credenciales/{credencial_id}", dependencies=[CSRF])
def credencial_eliminar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    try:
        servicio.eliminar(db, usuario=usuario, credencial_id=credencial_id, request=request)
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return {"ok": True}


@router.post("/credenciales/{credencial_id}/revelar", dependencies=[CSRF])
def credencial_revelar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    return _entregar(request, db, usuario, credencial_id, audit.CREDENCIAL_REVELADA)


@router.post("/credenciales/{credencial_id}/copiar", dependencies=[CSRF])
def credencial_copiar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    return _entregar(request, db, usuario, credencial_id, audit.CREDENCIAL_COPIADA)


def _entregar(
    request: Request, db: Session, usuario: Usuario, credencial_id: int, accion: str
) -> JSONResponse:
    try:
        datos = servicio.entregar_password(
            db, usuario=usuario, credencial_id=credencial_id, accion=accion,
            request=request, sesion_id=_sesion_id(request),
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return JSONResponse(datos, headers=SIN_CACHE)


@router.post("/credenciales/{credencial_id}/historial/{historial_id}/revelar", dependencies=[CSRF])
def historial_revelar(
    request: Request,
    credencial_id: int,
    historial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    try:
        datos = servicio.revelar_historial(
            db, usuario=usuario, credencial_id=credencial_id,
            historial_id=historial_id, request=request,
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return JSONResponse(datos, headers=SIN_CACHE)
