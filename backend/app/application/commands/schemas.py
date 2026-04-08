from __future__ import annotations

import base64
import ipaddress
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreateServerCommand(BaseModel):
    """Strict command for creating an inventory server."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, str_strip_whitespace=True)

    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=7, max_length=45)
    operating_system: str = Field(..., min_length=1, max_length=100)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        pattern = (
            r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        )
        if not re.fullmatch(pattern, value):
            raise ValueError("Invalid hostname format (RFC 1123)")
        return value.lower()

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"Invalid IP address: {exc}") from exc
        return value

    @field_validator("operating_system")
    @classmethod
    def validate_operating_system(cls, value: str) -> str:
        if re.search(r"[<>\"';\\]", value):
            raise ValueError("Operating system contains invalid characters")
        return value


class UpdateServerCommand(BaseModel):
    """Strict command for updating a server."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, str_strip_whitespace=True)

    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    ip_address: str | None = Field(default=None, min_length=7, max_length=45)
    operating_system: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("hostname", mode="before")
    @classmethod
    def validate_hostname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        pattern = (
            r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        )
        if not re.fullmatch(pattern, value):
            raise ValueError("Invalid hostname format (RFC 1123)")
        return value.lower()

    @field_validator("ip_address", mode="before")
    @classmethod
    def validate_ip_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"Invalid IP address: {exc}") from exc
        return value

    @field_validator("operating_system", mode="before")
    @classmethod
    def validate_operating_system(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.search(r"[<>\"';\\]", value):
            raise ValueError("Operating system contains invalid characters")
        return value

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> UpdateServerCommand:
        if self.hostname is None and self.ip_address is None and self.operating_system is None:
            raise ValueError("At least one field must be provided")
        return self


class CreateCredentialCommand(BaseModel):
    """Strict command for storing ciphertext returned by the frontend."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    server_id: str = Field(..., min_length=36, max_length=36)
    credential_username: str = Field(..., min_length=1, max_length=255)
    cipher_text_b64: str = Field(..., alias="cipher_text", min_length=1, max_length=8192)
    wrapped_dek_b64: str = Field(..., alias="wrapped_dek", min_length=1, max_length=1024)
    iv_b64: str = Field(..., alias="iv", min_length=1, max_length=48)
    auth_tag_b64: str = Field(..., alias="auth_tag", min_length=1, max_length=64)
    pbkdf2_salt_b64: str = Field(..., alias="pbkdf2_salt", min_length=1, max_length=64)
    pbkdf2_iterations: int = Field(default=600000, ge=100000, le=1000000)

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        try:
            uuid.UUID(value, version=4)
        except ValueError as exc:
            raise ValueError(f"Invalid UUID format: {exc}") from exc
        return value

    @field_validator(
        "cipher_text_b64",
        "wrapped_dek_b64",
        "iv_b64",
        "auth_tag_b64",
        "pbkdf2_salt_b64",
    )
    @classmethod
    def validate_base64(cls, value: str) -> str:
        try:
            base64.b64decode(value, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid base64 encoding: {exc}") from exc
        return value

    @property
    def cipher_text_bytes(self) -> bytes:
        return base64.b64decode(self.cipher_text_b64)

    @property
    def wrapped_dek_bytes(self) -> bytes:
        return base64.b64decode(self.wrapped_dek_b64)

    @property
    def iv_bytes(self) -> bytes:
        return base64.b64decode(self.iv_b64)

    @property
    def auth_tag_bytes(self) -> bytes:
        return base64.b64decode(self.auth_tag_b64)

    @property
    def pbkdf2_salt_bytes(self) -> bytes:
        return base64.b64decode(self.pbkdf2_salt_b64)