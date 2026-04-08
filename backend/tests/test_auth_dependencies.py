from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies.auth import RoleRequired, get_current_user
from app.domain.identity import AuthenticatedUser, Role


class _StubVerifier:
    async def verify_token(self, token: str) -> dict[str, Any]:
        assert token == "signed-token"
        return {
            "sub": "user-123",
            "preferred_username": "alice",
            "realm_roles": ["ADMIN", "EDITOR", "NOT_A_ROLE"],
        }


def test_get_current_user_maps_roles_to_identity() -> None:
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="signed-token",
    )

    user = asyncio.run(
        get_current_user(credentials=credentials, verifier=_StubVerifier()),
    )

    assert user == AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.ADMIN, Role.EDITOR}),
    )


def test_role_required_allows_authorized_user() -> None:
    dependency = RoleRequired(Role.ADMIN, Role.EDITOR)
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.EDITOR}),
    )

    result = asyncio.run(dependency(user))

    assert result is user


def test_role_required_rejects_unauthorized_user() -> None:
    dependency = RoleRequired(Role.ADMIN)
    user = AuthenticatedUser(
        sub="user-456",
        username="bob",
        roles=frozenset({Role.VIEWER}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dependency(user))

    assert exc_info.value.status_code == 403