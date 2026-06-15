"""Gestión de tokens de API de solo lectura (solo administradores)."""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import TokenApi, Usuario

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("tokens.gestionar"))


@router.get("/tokens")
def tokens_lista(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nuevo_token: str = "",
    msg: str = "",
):
    tokens = db.scalars(select(TokenApi).order_by(TokenApi.creado_en.desc())).all()
    return render(request, "tokens.html", {
        "usuario_actual": usuario, "tokens": tokens, "nuevo_token": nuevo_token, "msg": msg,
    })


@router.post("/tokens", dependencies=[Depends(verificar_csrf)])
def token_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    nombre: Annotated[str, Form()] = "",
):
    nombre = nombre.strip()
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
    # El valor en claro viaja una única vez en el redirect a la propia página.
    return RedirectResponse(f"/tokens?nuevo_token={quote(valor)}", status_code=303)


@router.post("/tokens/{token_id}/revocar", dependencies=[Depends(verificar_csrf)])
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
    return RedirectResponse(f"/tokens?msg={quote('Token revocado.')}", status_code=303)
