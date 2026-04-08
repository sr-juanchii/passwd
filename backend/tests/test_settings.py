from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import Settings


def test_settings_load_password_from_secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_file = tmp_path / "db_password.txt"
    secret_file.write_text("super-secret\n", encoding="utf-8")

    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret_file))

    settings = Settings()

    assert settings.database_password is not None
    assert settings.database_password.get_secret_value() == "super-secret"
    assert settings.oidc_jwks_url.endswith("/protocol/openid-connect/certs")
    assert settings.async_database_url == (
        "mysql+aiomysql://app_service:super-secret@mysql:3306/inventory_zk"
    )
