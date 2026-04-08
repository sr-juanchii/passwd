from __future__ import annotations

import base64
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.domain.entities.credential import CredentialEntity


class ServerResponse(BaseModel):
    """Read model for servers without ownership leakage."""

    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)

    id: str
    hostname: str
    ip_address: str
    operating_system: str
    created_at: datetime
    updated_at: datetime


class ServerListResponse(BaseModel):
    """Paginated list of servers."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ServerResponse]
    total: int
    page: int
    page_size: int


class CredentialResponse(BaseModel):
    """Read model for zero-knowledge credentials."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    server_id: str
    credential_username: str
    cipher_text: str
    wrapped_dek: str
    iv: str
    auth_tag: str
    pbkdf2_salt: str
    pbkdf2_iterations: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: CredentialEntity) -> CredentialResponse:
        return cls(
            id=entity.id,
            server_id=entity.server_id,
            credential_username=entity.credential_username,
            cipher_text=base64.b64encode(entity.cipher_text).decode("ascii"),
            wrapped_dek=base64.b64encode(entity.wrapped_dek).decode("ascii"),
            iv=base64.b64encode(entity.iv).decode("ascii"),
            auth_tag=base64.b64encode(entity.auth_tag).decode("ascii"),
            pbkdf2_salt=base64.b64encode(entity.pbkdf2_salt).decode("ascii"),
            pbkdf2_iterations=entity.pbkdf2_iterations,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


class CredentialListResponse(BaseModel):
    """Collection of credentials for a server."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[CredentialResponse]
    total: int