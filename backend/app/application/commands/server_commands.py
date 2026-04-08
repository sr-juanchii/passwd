from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.commands.schemas import CreateServerCommand, UpdateServerCommand
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class CreateServerHandler:
    """Persist a new server owned by the authenticated user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: CreateServerCommand, user: AuthenticatedUser) -> str:
        server_id = str(uuid.uuid4())
        entity = ServerEntity(
            id=server_id,
            hostname=command.hostname,
            ip_address=command.ip_address,
            operating_system=command.operating_system,
            owner_user_id=user.sub,
        )

        self._session.add(entity)
        await self._session.commit()

        logger.info(
            "Server created",
            extra={
                "server_id": server_id,
                "hostname": command.hostname,
                "user_id": user.sub,
                "action": "CREATE_SERVER",
            },
        )

        return server_id


class UpdateServerHandler:
    """Update a server with optional ownership restriction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        command: UpdateServerCommand,
        user: AuthenticatedUser,
    ) -> bool:
        update_data: dict[str, str] = {}
        if command.hostname is not None:
            update_data["hostname"] = command.hostname
        if command.ip_address is not None:
            update_data["ip_address"] = command.ip_address
        if command.operating_system is not None:
            update_data["operating_system"] = command.operating_system

        stmt = update(ServerEntity).where(ServerEntity.id == server_id)
        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)
        stmt = stmt.values(**update_data)

        result = await self._session.execute(stmt)
        await self._session.commit()

        rowcount = getattr(result, "rowcount", 0) or 0
        updated = rowcount > 0

        logger.info(
            "Server update attempted",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "updated": updated,
                "action": "UPDATE_SERVER",
            },
        )

        return updated


class DeleteServerHandler:
    """Delete a server with optional ownership restriction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, server_id: str, user: AuthenticatedUser) -> bool:
        stmt = delete(ServerEntity).where(ServerEntity.id == server_id)
        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        await self._session.commit()

        rowcount = getattr(result, "rowcount", 0) or 0
        deleted = rowcount > 0

        logger.info(
            "Server delete attempted",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "deleted": deleted,
                "action": "DELETE_SERVER",
            },
        )

        return deleted