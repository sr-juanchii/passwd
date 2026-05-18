from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class AccessLevel(enum.StrEnum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class ServerAccessEntity(Base):
    """Many-to-many relationship between users and servers with access levels."""

    __tablename__ = "server_access"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel),
        nullable=False,
        default=AccessLevel.VIEWER,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_server_user_access"),
    )

    def __repr__(self) -> str:
        return f"<ServerAccessEntity server={self.server_id} user={self.user_id} level={self.access_level}>"
