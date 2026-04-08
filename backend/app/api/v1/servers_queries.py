from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireViewer
from app.application.queries.schemas import ServerListResponse, ServerResponse
from app.application.queries.server_queries import GetServerHandler, ListServersHandler
from app.infrastructure.database.session import get_db_session

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get(
    "/",
    response_model=ServerListResponse,
    summary="Listar servidores",
    description="Lista los servidores del usuario autenticado. ADMIN ve todos.",
)
async def list_servers(
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 20,
) -> ServerListResponse:
    handler = ListServersHandler(session)
    return await handler.handle(user, page, page_size)


@router.get(
    "/{server_id}",
    response_model=ServerResponse,
    summary="Obtener servidor",
    description="Obtiene un servidor por ID. BOLA enforced.",
)
async def get_server(
    server_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServerResponse:
    handler = GetServerHandler(session)
    result = await handler.handle(server_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return result