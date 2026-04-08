from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Iterator

import pytest

from app.api.dependencies import auth as auth_module
from app.config.settings import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]

os.environ["DATABASE_HOST"] = "mysql"
os.environ["DATABASE_PORT"] = "3306"
os.environ["DATABASE_NAME"] = "inventory_zk"
os.environ["DATABASE_USER"] = "app_service"
os.environ["DATABASE_SSL_CA"] = str(_REPO_ROOT / "infrastructure" / "mysql" / "ssl" / "ca.pem")
os.environ["OIDC_ISSUER_URL"] = "http://keycloak:8080/realms/inventory"
os.environ["OIDC_AUDIENCE"] = "inventory-api"
os.environ["LOG_LEVEL"] = "INFO"

for _secret_var in ("DATABASE_PASSWORD", "DATABASE_PASSWORD_FILE", "OIDC_JWKS_URL"):
    os.environ.pop(_secret_var, None)


@pytest.fixture(autouse=True)
def _reset_runtime_state() -> Iterator[None]:
    get_settings.cache_clear()
    auth_module._jwt_verifier = None
    yield
    get_settings.cache_clear()
    auth_module._jwt_verifier = None