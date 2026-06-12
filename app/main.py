"""Punto de entrada de la aplicación.

Ejecutar en desarrollo:   uvicorn app.main:app --reload
Ejecutar en producción:   detrás de un proxy TLS (ver docker-compose.yml)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__, audit
from app.config import get_settings
from app.database import get_db, init_db
from app.deps import RedirigirLogin, render
from app.models import ROL_ADMIN, Usuario
from app.routes import audit_view, auth, credentials, inventory, users
from app.security.passwords import hashear_password
from app.security.sessions import purgar_sesiones_expiradas


class CabecerasSeguridadMiddleware(BaseHTTPMiddleware):
    """Cabeceras endurecidas para toda respuesta (CIS 16.x / OWASP)."""

    async def dispatch(self, request: Request, call_next):
        respuesta = await call_next(request)
        respuesta.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; form-action 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; object-src 'none'"
        )
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        respuesta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        respuesta.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        respuesta.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        if get_settings().cookie_secure:
            respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.url.path.startswith("/static"):
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta


class LimiteTamanoPeticionMiddleware(BaseHTTPMiddleware):
    """Rechaza cuerpos desproporcionados (OWASP API4 — consumo de recursos).

    La aplicación solo recibe formularios pequeños; cualquier cuerpo mayor
    al límite configurado (64 KB por defecto) se corta antes de procesarse.
    """

    async def dispatch(self, request: Request, call_next):
        largo = request.headers.get("content-length", "")
        if largo.isdigit() and int(largo) > get_settings().max_request_bytes:
            return JSONResponse({"detail": "La petición excede el tamaño permitido."}, status_code=413)
        return await call_next(request)


def _bootstrap_admin() -> None:
    """Crea el administrador inicial si la tabla de usuarios está vacía.

    Requiere PASSWD_ADMIN_USERNAME, PASSWD_ADMIN_EMAIL y PASSWD_ADMIN_PASSWORD.
    La cuenta nace con cambio de contraseña forzado y deberá enrolar MFA en
    su primer acceso, de modo que la credencial de arranque es de un solo uso.
    """
    settings = get_settings()
    db = next(get_db())
    try:
        if (db.scalar(select(func.count(Usuario.id))) or 0) > 0:
            return
        if not (settings.admin_username and settings.admin_email and settings.admin_password):
            return
        admin = Usuario(
            username=settings.admin_username.strip().lower(),
            email=settings.admin_email.strip().lower(),
            nombre_completo="Administrador inicial",
            password_hash=hashear_password(settings.admin_password),
            rol=ROL_ADMIN,
            debe_cambiar_password=True,
        )
        db.add(admin)
        db.flush()
        audit.registrar(db, audit.USUARIO_CREADO, username="sistema",
                        objeto_tipo="usuario", objeto_id=admin.id,
                        detalle=f"Administrador inicial {admin.username} creado en el arranque.")
        db.commit()
    finally:
        db.close()


def _mantenimiento_arranque() -> None:
    """Aplica retención de auditoría y purga sesiones vencidas (CIS 8.10)."""
    settings = get_settings()
    db = next(get_db())
    try:
        audit.purgar_antiguos(db, settings.audit_retention_days)
        purgar_sesiones_expiradas(db)
        db.commit()
    finally:
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url=None,  # sin documentación interactiva pública
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(CabecerasSeguridadMiddleware)
    app.add_middleware(LimiteTamanoPeticionMiddleware)

    init_db()
    _bootstrap_admin()
    _mantenimiento_arranque()

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    app.include_router(auth.router)
    app.include_router(inventory.router)
    app.include_router(credentials.router)
    app.include_router(users.router)
    app.include_router(audit_view.router)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"estado": "ok", "version": __version__})

    @app.exception_handler(RedirigirLogin)
    async def manejar_redireccion_login(request: Request, exc: RedirigirLogin):
        return RedirectResponse(exc.destino, status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def manejar_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (403, 404) and "text/html" in request.headers.get("accept", "text/html"):
            return render(request, "error.html",
                          {"codigo": exc.status_code, "detalle": exc.detail}, status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
