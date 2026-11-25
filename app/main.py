"""Punto de entrada de la aplicación.

Ejecutar en desarrollo:   uvicorn app.main:app --reload
Ejecutar en producción:   detrás de un proxy TLS (ver docker-compose.yml)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__, ajustes, audit
from app.config import get_settings, obsoletas_en_uso
from app.database import get_db, init_db
from app.deps import RedirigirLogin, render
from app.models import ROL_ADMIN, Usuario
from app.routes import (
    accesos,
    api,
    audit_view,
    auth,
    configuracion,
    credentials,
    importer,
    inventory,
    metrics,
    notes,
    search,
    tokens,
    users,
    vault,
)
from app.security.passwords import hashear_password
from app.security.sessions import purgar_sesiones_expiradas

logger = logging.getLogger(__name__)


class RefrescoConfiguracionMiddleware(BaseHTTPMiddleware):
    """Propaga los cambios de configuración a este proceso (multi-worker).

    Refresca el singleton de ``Settings`` desde la tabla ``configuracion`` como
    máximo una vez por TTL (ver ``app/ajustes.py``): la mayoría de peticiones
    solo comparan un reloj monótono. Los cambios hechos en este mismo proceso ya
    se aplican al instante en ``ajustes.guardar``; esto cubre los cambios de
    OTROS workers/instancias.
    """

    async def dispatch(self, request: Request, call_next):
        ajustes.refrescar_singleton()
        return await call_next(request)


# Prefijos que NO pertenecen a la interfaz clásica: las dos APIs, los estáticos
# y la sonda de salud. Todo lo demás que sirve esta aplicación es HTML de Jinja,
# y es lo que la 2.0 retira (rotura R1 de docs/plan-v2.0.md).
_PREFIJOS_NO_CLASICOS = ("/api/", "/static", "/healthz")
_DOC_RETIRADA = "https://github.com/sr-juanchii/passwd/blob/main/docs/plan-v2.0.md"


def _es_interfaz_clasica(ruta: str) -> bool:
    return not ruta.startswith(_PREFIJOS_NO_CLASICOS)


class CabecerasSeguridadMiddleware(BaseHTTPMiddleware):
    """Cabeceras endurecidas para toda respuesta (CIS 16.x / OWASP)."""

    async def dispatch(self, request: Request, call_next):
        respuesta = await call_next(request)
        # Aviso de retirada de la interfaz clásica (R1). Se marca aquí, en el
        # único punto por el que pasan todas las respuestas, en vez de decorar
        # las 62 rutas Jinja una a una.
        #
        # NO se emite «Sunset»: la RFC 8594 pide una fecha y la 2.0 no tiene
        # fecha comprometida. Inventar una sería peor que no ponerla.
        if _es_interfaz_clasica(request.url.path):
            respuesta.headers["Deprecation"] = "true"
            respuesta.headers["Link"] = f'<{_DOC_RETIRADA}>; rel="deprecation"'
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


class LimiteTamanoPeticionMiddleware:
    """Rechaza cuerpos desproporcionados (OWASP API4 — consumo de recursos).

    Middleware ASGI puro. Comprueba el `Content-Length` declarado y, además,
    pre-lee el cuerpo de forma acotada antes de pasarlo a la aplicación: así
    también corta peticiones `Transfer-Encoding: chunked` (sin `Content-Length`),
    que de otro modo eludirían el control. El cuerpo ya validado se reinyecta a
    la app sin volver a leer la red. En producción nginx aplica un límite
    equivalente como primera barrera.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = get_settings().max_request_bytes

        # Vía rápida: Content-Length declarado mayor al límite.
        for nombre, valor in scope.get("headers", []):
            if nombre == b"content-length" and valor.isdigit() and int(valor) > max_bytes:
                await self._responder_413(send)
                return

        # Pre-lectura acotada del cuerpo (cubre también chunked).
        cuerpo = bytearray()
        while True:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                break  # p. ej. http.disconnect: que lo gestione la aplicación
            cuerpo += mensaje.get("body", b"")
            if len(cuerpo) > max_bytes:
                await self._responder_413(send)
                return
            if not mensaje.get("more_body", False):
                break

        datos = bytes(cuerpo)
        entregado = False

        async def receive_reinyectado() -> Message:
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": datos, "more_body": False}
            return await receive()

        await self.app(scope, receive_reinyectado, send)

    @staticmethod
    async def _responder_413(send: Send) -> None:
        cuerpo = '{"detail":"La petición excede el tamaño permitido."}'.encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(cuerpo)).encode()),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": cuerpo})


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


# Cada cuánto se repite el mantenimiento mientras el proceso está en marcha.
INTERVALO_MANTENIMIENTO_S = 6 * 3600


def ejecutar_mantenimiento() -> None:
    """Aplica la retención de auditoría y purga lo caducado (CIS 8.10).

    Se ejecuta al arrancar y después periódicamente, de modo que un cambio de la
    retención desde la consola surte efecto sin reiniciar. Usa la configuración
    vigente (con los ajustes guardados ya aplicados). Idempotente.
    """
    from app.security import otp_correo

    settings = get_settings()
    db = next(get_db())
    try:
        audit.purgar_antiguos(db, settings.audit_retention_days)
        purgar_sesiones_expiradas(db)
        otp_correo.purgar_expirados(db)
        # Agentes (v1.4.0). Barrido de respaldo: la expiración de los trabajos
        # también se aplica al entregarlos y al consultarlos, porque con ventanas
        # de minutos un barrido cada 6 h llegaría tarde.
        from app.servicios.agentes import purgar_telemetria
        from app.servicios.rotacion import expirar_trabajos

        expirar_trabajos(db)
        purgar_telemetria(db)
        _avisar_si_falta_el_segundo_par(db)
        db.commit()
    finally:
        db.close()


def _avisar_si_falta_el_segundo_par(db) -> None:
    """Avisa si no hay administradores suficientes para la regla de dos pares.

    La gobernanza de rotación exige que autorice alguien distinto del
    solicitante. Con un solo administrador activo esa regla no se puede aplicar:
    toda rotación cae por la vía de emergencia, que queda marcada y pendiente de
    una revisión que tampoco puede hacer nadie más. Conviene saberlo antes de
    descubrirlo durante un incidente.
    """
    from app.servicios.rotacion import MIN_ADMINISTRADORES, administradores_activos

    activos = administradores_activos(db)
    if activos < MIN_ADMINISTRADORES:
        logger.warning(
            "Solo hay %d administrador(es) activo(s): la regla de dos pares de la rotación no se "
            "puede aplicar y toda rotación caerá por la vía de emergencia, marcada y pendiente de "
            "revisión. Cree un segundo administrador (ver docs/manual-administrador.md §4 bis).",
            activos,
        )


async def _mantenimiento_periodico() -> None:
    """Bucle de mantenimiento en segundo plano (uno por proceso)."""
    while True:
        await asyncio.sleep(INTERVALO_MANTENIMIENTO_S)
        try:
            await asyncio.to_thread(ejecutar_mantenimiento)
        except Exception:  # noqa: BLE001 — el mantenimiento nunca tumba el proceso
            logger.exception("Falló el mantenimiento periódico; se reintentará.")


@contextlib.asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    tarea = asyncio.create_task(_mantenimiento_periodico())
    try:
        yield
    finally:
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=_ciclo_de_vida,
        docs_url=None,  # sin documentación interactiva pública
        redoc_url=None,
        openapi_url=None,
    )
    # IP real tras el proxy TLS: si hay proxies de confianza declarados, se
    # confía en X-Forwarded-For/-Proto SOLO cuando la conexión procede de esas
    # IPs (anti-spoofing). Así la auditoría y el límite de tasa por IP operan
    # sobre el cliente real y no sobre nginx (hallazgo H-2 de la verificación).
    if settings.trusted_proxies.strip():
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        confiables = [p.strip() for p in settings.trusted_proxies.split(",") if p.strip()]
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=confiables)

    if settings.rate_limit_backend != "bd":
        logger.warning(
            "PASSWD_RATE_LIMIT_BACKEND=%s: el límite de tasa vive en la memoria de CADA proceso. "
            "Con varios workers o réplicas use \"bd\" para compartir el presupuesto.",
            settings.rate_limit_backend,
        )

    # Aviso de retirada de configuración obsoleta (R4). Solo si la herencia está
    # en efecto: una instalación limpia —o una que ya define la variable nueva—
    # no debe ver nada. Quien dependa de ella se entera ahora y no al actualizar
    # a la 2.0, cuando deje de aplicarse.
    #
    # El aviso habla de la HERENCIA, no de la variable: `PASSWD_NOTIFY_ENABLED`
    # conserva su significado propio (las alertas a los administradores) y
    # pedir que se sustituya dejaría a quien lo hiciera sin ellas.
    for antigua, nueva in obsoletas_en_uso():
        logger.warning(
            "PASSWD_%s está fijando PASSWD_%s; la versión 2.0 dejará de heredarla. Defina "
            "PASSWD_%s explícitamente (ver docs/referencia-configuracion.md).",
            antigua, nueva, nueva,
        )

    # El orden importa: el último en añadirse queda como capa MÁS EXTERNA. Se
    # pone CabecerasSeguridad de último para que decore TODAS las respuestas,
    # incluidas las cortocircuitadas por el límite de tamaño (p. ej. un 413).
    app.add_middleware(LimiteTamanoPeticionMiddleware)
    app.add_middleware(RefrescoConfiguracionMiddleware)
    app.add_middleware(CabecerasSeguridadMiddleware)

    init_db()
    _bootstrap_admin()
    # Aplica los overrides de configuración persistidos sobre el singleton, para
    # que este worker arranque ya con los ajustes vigentes (no solo los de env).
    _db = next(get_db())
    try:
        ajustes.inicializar(_db)
    finally:
        _db.close()
    # Después de aplicar los ajustes: la retención usa el valor configurado.
    ejecutar_mantenimiento()

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    app.include_router(auth.router)
    app.include_router(inventory.router)
    app.include_router(search.router)
    app.include_router(credentials.router)
    app.include_router(accesos.router)
    app.include_router(notes.router)
    app.include_router(vault.router)
    app.include_router(importer.router)
    app.include_router(users.router)
    app.include_router(metrics.router)
    app.include_router(tokens.router)
    app.include_router(configuracion.router)
    app.include_router(api.router)
    app.include_router(audit_view.router)

    # API JSON para el frontend Next.js (coexiste con la web Jinja).
    from app.api_web import router as api_web_router

    app.include_router(api_web_router)

    # API de los agentes de rotación (v1.4.0): Bearer por agente, 404 si están apagados.
    from app.api_agent import router as api_agent_router

    app.include_router(api_agent_router)

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
        cabeceras = getattr(exc, "headers", None)
        # Un detalle estructurado ``{mensaje, code}`` se aplana a ``detail`` (texto)
        # más ``code``, para que el cliente distinga el motivo sin romper a quien
        # solo lee ``detail``.
        if isinstance(exc.detail, dict) and "mensaje" in exc.detail:
            cuerpo = {"detail": exc.detail["mensaje"], "code": exc.detail.get("code")}
            return JSONResponse(cuerpo, status_code=exc.status_code, headers=cabeceras)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=cabeceras)

    return app


app = create_app()
