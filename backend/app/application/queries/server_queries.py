from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.queries.schemas import ServerListResponse, ServerResponse
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class ListServersHandler:
    """List servers, restricting rows to the owner for non-admin users."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        user: AuthenticatedUser,
        page: int = 1,
        page_size: int = 20,
    ) -> ServerListResponse:
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        base_stmt = select(ServerEntity)
        count_stmt = select(func.count(ServerEntity.id))

        if not user.is_admin:
            base_stmt = base_stmt.where(ServerEntity.owner_user_id == user.sub)
            count_stmt = count_stmt.where(ServerEntity.owner_user_id == user.sub)

        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one() or 0

        stmt = (
            base_stmt.order_by(ServerEntity.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        servers: Sequence[ServerEntity] = result.scalars().all()

        logger.info(
            "Servers listed",
            extra={
                "user_id": user.sub,
                "total": total,
                "page": page,
                "page_size": page_size,
                "action": "LIST_SERVERS",
            },
        )

        return ServerListResponse(
            items=[ServerResponse.model_validate(server, from_attributes=True) for server in servers],
            total=total,
            page=page,
            page_size=page_size,
        )


class GetServerHandler:
    """Return a single server if the caller is allowed to see it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        user: AuthenticatedUser,
    ) -> ServerResponse | None:
        stmt = select(ServerEntity).where(ServerEntity.id == server_id)

        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        server = result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Server access denied or not found",
                extra={
                    "server_id": server_id,
                    "user_id": user.sub,
                    "action": "GET_SERVER_DENIED",
                },
            )
            return None

        logger.info(
            "Server retrieved",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "action": "GET_SERVER",
            },
        )

        return ServerResponse.model_validate(server, from_attributes=True)