from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireViewer
from app.application.queries.credential_queries import (
    GetCredentialHandler,
    ListCredentialsHandler,
)
from app.application.queries.schemas import CredentialListResponse, CredentialResponse
from app.infrastructure.database.session import get_db_session

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get(
    "/server/{server_id}",
    response_model=CredentialListResponse,
    summary="Listar credenciales de un servidor",
    description="Lista credenciales cifradas. BOLA doble enforced.",
)
async def list_credentials(
    server_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CredentialListResponse:
    handler = ListCredentialsHandler(session)
    result = await handler.handle(server_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return result


@router.get(
    "/{credential_id}",
    response_model=CredentialResponse,
    summary="Obtener credencial cifrada",
    description="Obtiene una credencial cifrada. El descifrado ocurre en el frontend.",
)
async def get_credential(
    credential_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CredentialResponse:
    handler = GetCredentialHandler(session)
    result = await handler.handle(credential_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied",
        )
    return result