"""Administración de cuentas (solo rol admin) — CIS v8.1 controles 5 y 6.

- Altas con contraseña temporal generada y cambio forzado al primer acceso.
- Desactivación en lugar de borrado para preservar la trazabilidad.
- Reinicio de MFA y de contraseña con revocación inmediata de sesiones.
"""

from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import ROLES_VALIDOS, Usuario
from app.rbac import ETIQUETAS_ROL
from app.security.passwords import hashear_password
from app.security.recovery import eliminar_codigos
from app.security.sessions import revocar_sesiones_de_usuario

router = APIRouter()

ADMIN = Depends(requiere_permiso("usuarios.gestionar"))


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
    msg: str = "",
):
    usuarios = db.scalars(select(Usuario).order_by(Usuario.username)).all()
    return render(request, "usuarios.html", {
        "usuario_actual": usuario, "usuarios": usuarios, "roles": ROLES_VALIDOS,
        "etiquetas_rol": ETIQUETAS_ROL, "msg": msg,
    })


@router.get("/usuarios/nuevo")
def usuario_nuevo_form(request: Request, usuario: Annotated[Usuario, ADMIN]):
    return render(request, "usuario_nuevo.html", {"usuario_actual": usuario, "roles": ROLES_VALIDOS})


@router.post("/usuarios/nuevo", dependencies=[Depends(verificar_csrf)])
def usuario_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
    username: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    nombre_completo: Annotated[str, Form()] = "",
    rol: Annotated[str, Form()] = "operador",
):
    username = username.strip().lower()
    email = email.strip().lower()
    error = ""
    if not username or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        error = "Nombre de usuario inválido (letras, números, punto, guion y guion bajo)."
    elif rol not in ROLES_VALIDOS:
        error = "Rol inválido."
    elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        error = "Correo electrónico inválido."
    elif db.scalar(select(Usuario).where(func.lower(Usuario.username) == username)):
        error = "Ya existe un usuario con ese nombre."
    elif db.scalar(select(Usuario).where(func.lower(Usuario.email) == email)):
        error = "Ya existe un usuario con ese correo."
    if error:
        return render(request, "usuario_nuevo.html",
                      {"usuario_actual": usuario, "roles": ROLES_VALIDOS, "error": error}, status_code=400)

    password_temporal = _generar_password_temporal()
    nuevo = Usuario(
        username=username, email=email, nombre_completo=nombre_completo.strip(),
        password_hash=hashear_password(password_temporal), rol=rol,
        debe_cambiar_password=True,
    )
    db.add(nuevo)
    db.flush()
    audit.registrar(db, audit.USUARIO_CREADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=nuevo.id, detalle=f"{username} (rol {rol})")
    return render(request, "usuario_password_temporal.html", {
        "usuario_actual": usuario, "objetivo": nuevo, "password_temporal": password_temporal,
        "titulo": "Usuario creado",
    })


@router.post("/usuarios/{usuario_id}/desactivar", dependencies=[Depends(verificar_csrf)])
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
    return RedirectResponse(f"/usuarios?msg={quote(f'Usuario {objetivo.username} desactivado.')}", status_code=303)


@router.post("/usuarios/{usuario_id}/reactivar", dependencies=[Depends(verificar_csrf)])
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
    return RedirectResponse(f"/usuarios?msg={quote(f'Usuario {objetivo.username} reactivado.')}", status_code=303)


@router.post("/usuarios/{usuario_id}/reset-password", dependencies=[Depends(verificar_csrf)])
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
    return render(request, "usuario_password_temporal.html", {
        "usuario_actual": usuario, "objetivo": objetivo, "password_temporal": password_temporal,
        "titulo": "Contraseña restablecida",
    })


@router.post("/usuarios/{usuario_id}/reset-mfa", dependencies=[Depends(verificar_csrf)])
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
    return RedirectResponse(f"/usuarios?msg={quote(f'MFA reiniciado para {objetivo.username}.')}", status_code=303)


@router.post("/usuarios/{usuario_id}/rol", dependencies=[Depends(verificar_csrf)])
def usuario_cambiar_rol(
    request: Request,
    usuario_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, ADMIN],
    rol: Annotated[str, Form()] = "",
):
    objetivo = _obtener_usuario_o_404(db, usuario_id)
    if objetivo.id == usuario.id:
        raise HTTPException(status_code=400, detail="No puede cambiar su propio rol.")
    if rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail="Rol inválido.")
    anterior = objetivo.rol
    objetivo.rol = rol
    revocar_sesiones_de_usuario(db, objetivo.id)
    audit.registrar(db, audit.USUARIO_ACTUALIZADO, request=request, usuario=usuario,
                    objeto_tipo="usuario", objeto_id=objetivo.id,
                    detalle=f"Rol de {objetivo.username}: {anterior} → {rol}; sesiones revocadas")
    return RedirectResponse(f"/usuarios?msg={quote(f'Rol de {objetivo.username} actualizado.')}", status_code=303)
