from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireAdmin, RequireEditor
from app.application.commands.schemas import CreateServerCommand, UpdateServerCommand
from app.application.commands.server_commands import (
    CreateServerHandler,
    DeleteServerHandler,
    UpdateServerHandler,
)
from app.infrastructure.database.session import get_db_session

router = APIRouter(prefix="/servers", tags=["servers"])


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, str],
    summary="Crear servidor",
    description="Registra un nuevo servidor en el inventario. Requiere rol ADMIN o EDITOR.",
)
async def create_server(
    command: CreateServerCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    handler = CreateServerHandler(session)
    server_id = await handler.handle(command, user)
    return {"id": server_id, "status": "created"}


@router.put(
    "/{server_id}",
    response_model=dict[str, str],
    summary="Actualizar servidor",
    description="Actualiza un servidor existente. BOLA enforced.",
)
async def update_server(
    server_id: str,
    command: UpdateServerCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    handler = UpdateServerHandler(session)
    updated = await handler.handle(server_id, command, user)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return {"id": server_id, "status": "updated"}


@router.delete(
    "/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar servidor",
    description="Elimina un servidor y sus credenciales. Solo ADMIN.",
)
async def delete_server(
    server_id: str,
    user: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    handler = DeleteServerHandler(session)
    deleted = await handler.handle(server_id, user)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
