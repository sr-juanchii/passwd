"""Dependencias FastAPI: autenticación, autorización, CSRF y plantillas."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.database import get_db
from app.exceptions import RedirigirLogin
from app.models import ETAPA_ACTIVA, SesionWeb, Usuario
from app.rbac import ETIQUETAS_ROL, tiene_permiso
from app.security.sessions import COOKIE_SESION, buscar_sesion_valida

__all__ = ["RedirigirLogin"]

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _sesion_de_cookie(request: Request, db: Session) -> SesionWeb | None:
    token = request.cookies.get(COOKIE_SESION, "")
    return buscar_sesion_valida(db, token)


def sesion_activa(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
    """Exige una sesión que completó contraseña + MFA y un usuario activo."""
    sesion = _sesion_de_cookie(request, db)
    if sesion is None or sesion.etapa != ETAPA_ACTIVA:
        raise RedirigirLogin()
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        sesion.revocada_en = sesion.ultima_actividad
        raise RedirigirLogin()
    request.state.sesion = sesion
    return sesion


def en_etapa(etapa: str):
    """Dependencia para los pasos previos del login (cambio de clave, MFA)."""

    def _dep(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
        sesion = _sesion_de_cookie(request, db)
        if sesion is None or sesion.etapa != etapa:
            raise RedirigirLogin()
        usuario = db.get(Usuario, sesion.usuario_id)
        if usuario is None or not usuario.activo:
            raise RedirigirLogin()
        request.state.sesion = sesion
        return sesion

    return _dep


def usuario_actual(
    sesion: Annotated[SesionWeb, Depends(sesion_activa)],
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None  # garantizado por sesion_activa
    return usuario


def requiere_permiso(permiso: str):
    """Dependencia de autorización; los rechazos quedan auditados."""

    def _dep(
        request: Request,
        usuario: Annotated[Usuario, Depends(usuario_actual)],
        db: Annotated[Session, Depends(get_db)],
    ) -> Usuario:
        if not tiene_permiso(usuario.rol, permiso):
            audit.registrar(
                db,
                audit.ACCESO_DENEGADO,
                request=request,
                usuario=usuario,
                detalle=f"Permiso requerido: {permiso} ({request.method} {request.url.path})",
                exito=False,
            )
            # Se confirma aquí: el rollback posterior de la petición fallida
            # no debe borrar la evidencia del intento denegado.
            db.commit()
            raise HTTPException(status_code=403, detail="No tiene permisos para esta operación.")
        return usuario

    return _dep


async def verificar_csrf(
    request: Request,
    sesion: Annotated[SesionWeb, Depends(sesion_activa)],
) -> None:
    """Valida el token anti-CSRF de los formularios autenticados."""
    formulario = await request.form()
    enviado = str(formulario.get("csrf_token", ""))
    if not enviado or not hmac.compare_digest(enviado, sesion.csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido o ausente.")


def render(request: Request, plantilla: str, contexto: dict | None = None, status_code: int = 200):
    """Renderiza una plantilla inyectando el contexto global de la aplicación."""
    sesion = getattr(request.state, "sesion", None)
    ctx: dict = {
        "app_name": get_settings().app_name,
        "usuario_actual": None,
        "csrf_token": sesion.csrf_token if sesion is not None else "",
        "puede": lambda _p: False,
        "etiquetas_rol": ETIQUETAS_ROL,
    }
    if contexto:
        ctx.update(contexto)
    usuario = ctx.get("usuario_actual")
    if usuario is not None:
        ctx["puede"] = lambda p, _rol=usuario.rol: tiene_permiso(_rol, p)
    return templates.TemplateResponse(request=request, name=plantilla, context=ctx, status_code=status_code)
