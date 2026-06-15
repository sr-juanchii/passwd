"""Administración de cuentas en JSON (solo rol admin).

Replica ``app/routes/users.py``: altas con contraseña temporal y cambio
forzado, desactivación/reactivación, reinicio de MFA y de contraseña con
revocación de sesiones, y cambio de rol. Todo auditado.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.api_web.serializers import serializar_usuario
from app.database import get_db
from app.models import ROLES_VALIDOS, Usuario
from app.notifications import enviar_alerta
from app.security.passwords import hashear_password
from app.security.recovery import eliminar_codigos
from app.security.sessions import revocar_sesiones_de_usuario

router = APIRouter()

ADMIN = Depends(requiere_permiso_json("usuarios.gestionar"))
CSRF = Depends(verificar_csrf_json)


class UsuarioCrear(BaseModel):
    username: str = ""
    email: str = ""
    nombre_completo: str = ""
    rol: str = "operador"


class RolInput(BaseModel):
    rol: str = ""


def _generar_password_temporal() -> str:
    return secrets.token_urlsafe(14)


def _obtener_usuario_o_404(db: Session, usuario_id: int) -> Usuario:
    objetivo = db.get(Usuario, usuario_id)
    if objetivo is None:
        raise HTTPException(status_code=404, detail="El usuario no existe.")
    return objetivo


@router.get("/usuarios")
def usuarios_lista(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
):
    usuarios = db.scalars(select(Usuario).order_by(Usuario.username)).all()
    return {"usuarios": [serializar_usuario(u) for u in usuarios]}


@router.post("/usuarios", dependencies=[CSRF])
def usuario_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
    cuerpo: UsuarioCrear,
):
    username = cuerpo.username.strip().lower()
    email = cuerpo.email.strip().lower()
    if not username or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400,
                            detail="Nombre de usuario inválido (letras, números, punto, guion y guion bajo).")
    if cuerpo.rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail="Rol inválido.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="Correo electrónico inválido.")
    if db.scalar(select(Usuario).where(func.lower(Usuario.username) == username)):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese nombre.")
    if db.scalar(select(Usuario).where(func.lower(Usuario.email) == email)):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo.")

    password_temporal = _generar_password_temporal()
    nuevo = Usuario(
        username=username, email=email, nombre_completo=cuerpo.nombre_completo.strip(),
        password_hash=hashear_password(password_temporal), rol=cuerpo.rol,
        debe_cambiar_password=True,
    )
    db.add(nuevo)
    db.flush()
    audit.registrar(db, audit.USUARIO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=nuevo.id, detalle=f"{username} (rol {cuerpo.rol})")
    enviar_alerta("Nuevo usuario creado",
                  f"«{usuario.username}» creó la cuenta «{username}» con rol {cuerpo.rol}.")
    return {"username": nuevo.username, "password_temporal": password_temporal}


@router.post("/usuarios/{usuario_id}/desactivar", dependencies=[CSRF])
def usuario_desactivar(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    if objetivo.id == usuario.id:
        raise HTTPException(status_code=400, detail="No puede desactivar su propia cuenta.")
    objetivo.activo = False
    revocadas = revocar_sesiones_de_usuario(db, objetivo.id)
    audit.registrar(db, audit.USUARIO_DESACTIVADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id,
                    detalle=f"{objetivo.username}; {revocadas} sesión(es) revocada(s)")
    return {"ok": True}


@router.post("/usuarios/{usuario_id}/reactivar", dependencies=[CSRF])
def usuario_reactivar(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    objetivo.activo = True
    objetivo.intentos_fallidos = 0
    objetivo.bloqueado_hasta = None
    audit.registrar(db, audit.USUARIO_REACTIVADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id, detalle=objetivo.username)
    return {"ok": True}


@router.post("/usuarios/{usuario_id}/reset-password", dependencies=[CSRF])
def usuario_reset_password(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    password_temporal = _generar_password_temporal()
    objetivo.password_hash = hashear_password(password_temporal)
    objetivo.debe_cambiar_password = True
    objetivo.intentos_fallidos = 0
    objetivo.bloqueado_hasta = None
    revocar_sesiones_de_usuario(db, objetivo.id)
    audit.registrar(db, audit.USUARIO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id,
                    detalle=f"Contraseña temporal emitida para {objetivo.username}; sesiones revocadas")
    return {"username": objetivo.username, "password_temporal": password_temporal}


@router.post("/usuarios/{usuario_id}/reset-mfa", dependencies=[CSRF])
def usuario_reset_mfa(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    objetivo.mfa_habilitado = False
    objetivo.totp_secret_cifrado = None
    objetivo.ultimo_otp_usado = None
    eliminar_codigos(db, objetivo.id)
    revocar_sesiones_de_usuario(db, objetivo.id)
    audit.registrar(db, audit.MFA_REINICIADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id,
                    detalle=f"{objetivo.username} deberá enrolar MFA de nuevo; sesiones revocadas")
    return {"ok": True}


@router.post("/usuarios/{usuario_id}/rol", dependencies=[CSRF])
def usuario_cambiar_rol(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
    cuerpo: RolInput,
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    if objetivo.id == usuario.id:
        raise HTTPException(status_code=400, detail="No puede cambiar su propio rol.")
    if cuerpo.rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail="Rol inválido.")
    anterior = objetivo.rol
    objetivo.rol = cuerpo.rol
    revocar_sesiones_de_usuario(db, objetivo.id)
    audit.registrar(db, audit.USUARIO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id,
                    detalle=f"Rol de {objetivo.username}: {anterior} → {cuerpo.rol}; sesiones revocadas")
    return {"ok": True}
