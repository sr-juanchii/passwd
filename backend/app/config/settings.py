from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment or Docker secrets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    app_name: str = "ZK Inventory API"
    app_version: str = "0.1.0"
    debug: bool = False

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_host: str = Field(default="mysql", alias="DATABASE_HOST")
    database_port: int = Field(default=3306, alias="DATABASE_PORT")
    database_name: str = Field(default="inventory_zk", alias="DATABASE_NAME")
    database_user: str = Field(default="app_service", alias="DATABASE_USER")
    database_password: SecretStr | None = Field(default=None, alias="DATABASE_PASSWORD")
    database_password_file: Path | None = Field(default=None, alias="DATABASE_PASSWORD_FILE")
    database_ssl_ca: str = Field(default="/etc/mysql/ssl/ca.pem", alias="DATABASE_SSL_CA")

    oidc_issuer_url: str = Field(
        default="http://keycloak:8080/realms/inventory",
        alias="OIDC_ISSUER_URL",
    )
    oidc_audience: str = Field(default="inventory-api", alias="OIDC_AUDIENCE")
    oidc_jwks_url: str = Field(default="", alias="OIDC_JWKS_URL")

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:4200"],
        alias="CORS_ALLOWED_ORIGINS",
    )

    @model_validator(mode="after")
    def _hydrate(self) -> Settings:
        if self.database_password is None and self.database_password_file is not None:
            if self.database_password_file.is_file():
                secret = self.database_password_file.read_text(encoding="utf-8").strip()
                if secret:
                    self.database_password = SecretStr(secret)

        if not self.oidc_jwks_url:
            self.oidc_jwks_url = (
                f"{self.oidc_issuer_url.rstrip('/')}"
                "/protocol/openid-connect/certs"
            )

        return self

    @staticmethod
    def _resolve_jwks_url(issuer_url: str) -> str:
        return f"{issuer_url.rstrip('/')}/protocol/openid-connect/certs"

    @field_validator("oidc_jwks_url", mode="before")
    @classmethod
    def build_jwks_url(cls, value: str, info: ValidationInfo) -> str:
        if value:
            return value
        issuer = info.data.get("oidc_issuer_url", "")
        return cls._resolve_jwks_url(str(issuer))

    @property
    def async_database_url(self) -> str:
        password = (
            self.database_password.get_secret_value()
            if self.database_password is not None
            else ""
        )
        credential_segment = f":{password}" if password else ""
        return (
            f"mysql+aiomysql://{self.database_user}{credential_segment}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
