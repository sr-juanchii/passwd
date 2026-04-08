from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from .server import ServerEntity


class CredentialEntity(Base):
    """Zero-knowledge credential entity storing opaque ciphertext bytes."""

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    credential_username: Mapped[str] = mapped_column(String(255), nullable=False)
    cipher_text: Mapped[bytes] = mapped_column(LargeBinary(4096), nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary(512), nullable=False)
    iv: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    auth_tag: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    pbkdf2_salt: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    pbkdf2_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=600000)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    server: Mapped[ServerEntity] = relationship(back_populates="credentials")

    def __repr__(self) -> str:
        return f"<CredentialEntity id={self.id!s} server_id={self.server_id!s}>"