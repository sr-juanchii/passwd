from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireEditor
from app.application.commands.credential_commands import CreateCredentialHandler
from app.application.commands.schemas import CreateCredentialCommand
from app.infrastructure.database.session import get_db_session

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, str],
    summary="Almacenar credencial cifrada",
    description=(
        "Almacena una credencial cifrada por el frontend. "
        "El backend NUNCA ve la contraseña en texto claro. "
        "Requiere rol ADMIN o EDITOR."
    ),
)
async def create_credential(
    command: CreateCredentialCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    handler = CreateCredentialHandler(session)
    try:
        credential_id = await handler.handle(command, user)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"id": credential_id, "status": "stored"}