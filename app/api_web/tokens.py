"""Tokens de API de solo lectura en JSON (solo administradores).

Replica ``app/routes/tokens.py``: el valor del token se entrega una única vez al
crearlo; en la BD solo vive su hash SHA-256.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.api_web.serializers import serializar_token
from app.database import get_db
from app.models import TokenApi, Usuario

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("tokens.gestionar"))
CSRF = Depends(verificar_csrf_json)


class TokenCrear(BaseModel):
    nombre: str = ""


@router.get("/tokens")
def tokens_lista(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    tokens = db.scalars(select(TokenApi).order_by(TokenApi.creado_en.desc())).all()
    return {"tokens": [serializar_token(t) for t in tokens]}


@router.post("/tokens", dependencies=[CSRF])
def token_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: TokenCrear,
):
    nombre = cuerpo.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del token es obligatorio.")
    valor = secrets.token_urlsafe(32)  # se muestra una sola vez
    db.add(TokenApi(
        nombre=nombre,
        token_hash=hashlib.sha256(valor.encode("ascii")).hexdigest(),
        creado_por_id=usuario.id,
    ))
    audit.registrar(db, audit.TOKEN_CREADO, request=request, usuario=usuario,
                    objeto_tipo="token_api", detalle=f"Token «{nombre}» creado (solo lectura)")
    return {"token": valor}


@router.post("/tokens/{token_id}/revocar", dependencies=[CSRF])
def token_revocar(
    request: Request,
    token_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    token = db.get(TokenApi, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="El token no existe.")
    token.activo = False
    audit.registrar(db, audit.TOKEN_REVOCADO, request=request, usuario=usuario,
                    objeto_tipo="token_api", objeto_id=token.id, detalle=f"Token «{token.nombre}» revocado")
    return {"ok": True}
