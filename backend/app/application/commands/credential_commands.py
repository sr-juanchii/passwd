from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.commands.schemas import CreateCredentialCommand
from app.domain.entities.credential import CredentialEntity
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class CreateCredentialHandler:
    """Persist opaque ciphertext bytes for a server credential."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: CreateCredentialCommand, user: AuthenticatedUser) -> str:
        stmt = select(ServerEntity).where(ServerEntity.id == command.server_id)
        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        server = result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Credential creation denied: server not found or access denied",
                extra={
                    "server_id": command.server_id,
                    "user_id": user.sub,
                    "action": "CREATE_CREDENTIAL_DENIED",
                },
            )
            raise PermissionError(f"Server {command.server_id} not found or access denied")

        credential_id = str(uuid.uuid4())
        entity = CredentialEntity(
            id=credential_id,
            server_id=command.server_id,
            owner_user_id=user.sub,
            credential_username=command.credential_username,
            cipher_text=command.cipher_text_bytes,
            wrapped_dek=command.wrapped_dek_bytes,
            iv=command.iv_bytes,
            auth_tag=command.auth_tag_bytes,
            pbkdf2_salt=command.pbkdf2_salt_bytes,
            pbkdf2_iterations=command.pbkdf2_iterations,
        )

        self._session.add(entity)
        await self._session.commit()

        logger.info(
            "Credential stored (Zero-Knowledge)",
            extra={
                "credential_id": credential_id,
                "server_id": command.server_id,
                "user_id": user.sub,
                "action": "CREATE_CREDENTIAL",
            },
        )

        return credential_id