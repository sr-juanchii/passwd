"""API JSON (`/api/web`) consumida por el frontend Next.js.

Reúne los sub-routers (auth, inventario, credenciales, accesos, notas, búsqueda,
usuarios, tokens, auditoría, métricas e importación) bajo el prefijo común y
reutiliza el modelo de seguridad de la aplicación (sesión por cookie, CSRF por
cabecera, RBAC y control de acceso por objeto).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api_web import (
    accesos,
    audit,
    auth,
    configuracion,
    credentials,
    exporter,
    importer,
    inventory,
    metrics,
    notes,
    search,
    tokens,
    users,
    vault,
)

router = APIRouter(prefix="/api/web", tags=["web"])

for _modulo in (
    auth,
    inventory,
    credentials,
    search,
    accesos,
    notes,
    users,
    tokens,
    configuracion,
    audit,
    metrics,
    importer,
    exporter,
    vault,
):
    router.include_router(_modulo.router)

__all__ = ["router"]
