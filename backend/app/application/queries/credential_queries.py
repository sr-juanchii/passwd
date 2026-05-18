from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.queries.schemas import CredentialListResponse, CredentialResponse
from app.domain.entities.credential import CredentialEntity
from app.domain.entities.server import ServerEntity
from app.domain.entities.server_access import ServerAccessEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class ListCredentialsHandler:
    """List credentials for a server after verifying server ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        user: AuthenticatedUser,
    ) -> CredentialListResponse | None:
        server_stmt = select(ServerEntity).where(ServerEntity.id == server_id)

        if not user.is_admin:
            server_stmt = server_stmt.join(
                ServerAccessEntity,
                ServerAccessEntity.server_id == ServerEntity.id
            ).where(ServerAccessEntity.user_id == user.sub)

        server_result = await self._session.execute(server_stmt)
        server = server_result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Credential listing denied: server not found or access denied",
                extra={
                    "server_id": server_id,
                    "user_id": user.sub,
                    "action": "LIST_CREDENTIALS_DENIED",
                },
            )
            return None

        credential_stmt = select(CredentialEntity).where(
            CredentialEntity.server_id == server_id,
        )
        if not user.is_admin:
            credential_stmt = credential_stmt.join(
                ServerAccessEntity,
                ServerAccessEntity.server_id == CredentialEntity.server_id
            ).where(ServerAccessEntity.user_id == user.sub)

        result = await self._session.execute(credential_stmt)
        credentials = result.scalars().all()

        logger.info(
            "Credentials listed (Zero-Knowledge)",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "count": len(credentials),
                "action": "LIST_CREDENTIALS",
            },
        )

        return CredentialListResponse(
            items=[CredentialResponse.from_entity(credential) for credential in credentials],
            total=len(credentials),
        )


class GetCredentialHandler:
    """Return a single encrypted credential if the caller owns it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        credential_id: str,
        user: AuthenticatedUser,
    ) -> CredentialResponse | None:
        stmt = select(CredentialEntity).where(CredentialEntity.id == credential_id)

        if not user.is_admin:
            stmt = stmt.join(
                ServerAccessEntity,
                ServerAccessEntity.server_id == CredentialEntity.server_id
            ).where(ServerAccessEntity.user_id == user.sub)

        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()

        if credential is None:
            logger.warning(
                "Credential access denied or not found",
                extra={
                    "credential_id": credential_id,
                    "user_id": user.sub,
                    "action": "GET_CREDENTIAL_DENIED",
                },
            )
            return None

        logger.info(
            "Credential retrieved (Zero-Knowledge)",
            extra={
                "credential_id": credential_id,
                "user_id": user.sub,
                "action": "GET_CREDENTIAL",
            },
        )

        return CredentialResponse.from_entity(credential)