"""Dependencias FastAPI para la API JSON (`/api/web`).

Reutilizan exactamente el modelo de seguridad de ``app/deps.py`` (sesión por
cookie, RBAC, control de acceso por objeto y auditoría), pero en lugar de
redirigir a la pantalla de acceso responden errores JSON con el código HTTP
apropiado, como espera un cliente de API (frontend Next.js).
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.models import ETAPA_ACTIVA, SesionWeb, Usuario
from app.rbac import tiene_permiso
from app.security.sessions import COOKIE_SESION, buscar_sesion_valida


def _sesion_de_cookie(request: Request, db: Session) -> SesionWeb | None:
    token = request.cookies.get(COOKIE_SESION, "")
    return buscar_sesion_valida(db, token)


def sesion_activa_json(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
    """Exige una sesión que completó contraseña + MFA y un usuario activo (401 JSON)."""
    sesion = _sesion_de_cookie(request, db)
    if sesion is None or sesion.etapa != ETAPA_ACTIVA:
        raise HTTPException(status_code=401, detail="No autenticado")
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        sesion.revocada_en = sesion.ultima_actividad
        # Se confirma aquí: el rollback posterior del 401 no debe deshacer
        # la revocación de la sesión de un usuario desactivado.
        db.commit()
        raise HTTPException(status_code=401, detail="No autenticado")
    request.state.sesion = sesion
    return sesion


def en_etapa_json(etapa: str):
    """Dependencia JSON para los pasos previos del login (cambio de clave, MFA)."""

    def _dep(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
        sesion = _sesion_de_cookie(request, db)
        if sesion is None or sesion.etapa != etapa:
            raise HTTPException(status_code=403, detail="Etapa de sesión no válida para esta operación.")
        usuario = db.get(Usuario, sesion.usuario_id)
        if usuario is None or not usuario.activo:
            raise HTTPException(status_code=401, detail="No autenticado")
        request.state.sesion = sesion
        return sesion

    return _dep


def usuario_actual_json(
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None  # garantizado por sesion_activa_json
    return usuario


def requiere_permiso_json(permiso: str):
    """Dependencia de autorización JSON; los rechazos quedan auditados (403)."""

    def _dep(
        request: Request,
        usuario: Annotated[Usuario, Depends(usuario_actual_json)],
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


def verificar_csrf_json(
    request: Request,
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
) -> None:
    """Valida el token anti-CSRF leyéndolo de la cabecera ``X-CSRF-Token``."""
    enviado = request.headers.get("x-csrf-token", "")
    if not enviado or not hmac.compare_digest(enviado, sesion.csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido o ausente.")
