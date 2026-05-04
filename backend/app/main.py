from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import api_v1_router
from app.api.dependencies.auth import init_jwt_verifier
from app.config.settings import Settings, get_settings
from app.infrastructure.database.session import dispose_db_engine, init_db_engine
from app.shared.logging_config import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and tear down shared runtime resources."""

    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db_engine(settings)
    init_jwt_verifier(settings)
    logger.info("Application started", extra={"version": settings.app_version})

    yield

    await dispose_db_engine()
    logger.info("Application shutdown complete")


def _register_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_security_headers(
        _request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(_request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


@lru_cache(maxsize=1)
def _create_app() -> FastAPI:
    """Build the FastAPI application instance with singleton caching."""

    settings: Settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "backend", "frontend", "testserver"],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    _register_security_headers(app)

    app.include_router(api_v1_router)

    @app.get("/health", tags=["infra"], include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "healthy", "version": settings.app_version}

    return app


def create_app() -> FastAPI:
    """Return the cached FastAPI application instance."""
    return _create_app()


app = create_app()
