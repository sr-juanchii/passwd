from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.credentials_queries import router as credentials_queries_router
from app.api.v1.credentials import router as credentials_router
from app.api.v1.servers_queries import router as servers_queries_router
from app.api.v1.servers import router as servers_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(servers_router)
api_v1_router.include_router(credentials_router)
api_v1_router.include_router(servers_queries_router)
api_v1_router.include_router(credentials_queries_router)

__all__ = ["api_v1_router"]
