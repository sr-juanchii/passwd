from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1.credentials_queries import get_credential
from app.api.v1.servers_queries import get_server
from app.application.queries.credential_queries import GetCredentialHandler, ListCredentialsHandler
from app.application.queries.schemas import CredentialResponse, ServerResponse
from app.application.queries.server_queries import GetServerHandler, ListServersHandler
from app.domain.entities.credential import CredentialEntity
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser, Role
from app.main import app


@dataclass
class _FakeScalarResult:
    items: list[Any]

    def all(self) -> list[Any]:
        return self.items


@dataclass
class _FakeResult:
    scalar_value: Any | None = None
    items: list[Any] = field(default_factory=list)

    def scalar_one(self) -> Any:
        if self.scalar_value is None:
            raise RuntimeError("scalar_one called without value")
        return self.scalar_value

    def scalar_one_or_none(self) -> Any | None:
        return self.scalar_value

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self.items)


class _QueuedSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.executed_statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed_statements.append(statement)
        if not self._results:
            raise RuntimeError("No queued result available")
        return self._results.pop(0)


def _make_server(server_id: str, owner_user_id: str = "user-123") -> ServerEntity:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ServerEntity(
        id=server_id,
        hostname="web-server",
        ip_address="10.0.0.10",
        operating_system="Ubuntu 22.04",
        owner_user_id=owner_user_id,
        created_at=now,
        updated_at=now,
    )


def _make_credential(credential_id: str, server_id: str, owner_user_id: str = "user-123") -> CredentialEntity:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CredentialEntity(
        id=credential_id,
        server_id=server_id,
        owner_user_id=owner_user_id,
        credential_username="root",
        cipher_text=b"cipher",
        wrapped_dek=b"wrapped",
        iv=b"iv-bytes-1234",
        auth_tag=b"auth-tag-12345678",
        pbkdf2_salt=b"salt-bytes-1234567890123456",
        pbkdf2_iterations=600000,
        created_at=now,
        updated_at=now,
    )


def test_api_v1_query_routes_registered() -> None:
    paths = {getattr(route, "path") for route in app.routes if getattr(route, "path", None) is not None}

    assert "/api/v1/servers/" in paths
    assert "/api/v1/servers/{server_id}" in paths
    assert "/api/v1/credentials/server/{server_id}" in paths
    assert "/api/v1/credentials/{credential_id}" in paths


def test_server_response_from_entity() -> None:
    server = _make_server("00000000-0000-0000-0000-000000000001")
    response = ServerResponse.model_validate(server, from_attributes=True)

    assert response.hostname == "web-server"


def test_credential_response_encodes_binary_fields() -> None:
    credential = _make_credential(
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    )

    response = CredentialResponse.from_entity(credential)

    assert response.cipher_text == base64.b64encode(b"cipher").decode("ascii")
    assert response.wrapped_dek == base64.b64encode(b"wrapped").decode("ascii")
    assert response.iv == base64.b64encode(b"iv-bytes-1234").decode("ascii")
    assert response.auth_tag == base64.b64encode(b"auth-tag-12345678").decode("ascii")
    assert response.pbkdf2_salt == base64.b64encode(b"salt-bytes-1234567890123456").decode("ascii")


def test_list_servers_clamps_page_size_and_filters_owner() -> None:
    server = _make_server("00000000-0000-0000-0000-000000000001")
    session: Any = _QueuedSession([
        _FakeResult(scalar_value=1),
        _FakeResult(items=[server]),
    ])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    response = asyncio.run(ListServersHandler(session).handle(user, page=2, page_size=500))

    assert response.total == 1
    assert response.page == 2
    assert response.page_size == 100
    assert response.items[0].hostname == "web-server"

    count_sql = str(session.executed_statements[0].compile(compile_kwargs={"literal_binds": True}))
    list_sql = str(session.executed_statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "owner_user_id" in count_sql
    assert "owner_user_id" in list_sql


def test_list_servers_admin_sees_all_records() -> None:
    server = _make_server("00000000-0000-0000-0000-000000000001", owner_user_id="other-user")
    session: Any = _QueuedSession([
        _FakeResult(scalar_value=1),
        _FakeResult(items=[server]),
    ])
    user = AuthenticatedUser(
        sub="admin-user",
        username="admin",
        roles=frozenset({Role.ADMIN}),
    )

    response = asyncio.run(ListServersHandler(session).handle(user, page=1, page_size=10))

    assert response.total == 1
    list_sql = str(session.executed_statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "WHERE" not in list_sql


def test_get_server_returns_none_for_foreign_resource() -> None:
    session: Any = _QueuedSession([_FakeResult(scalar_value=None)])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    result = asyncio.run(GetServerHandler(session).handle("server-id", user))

    assert result is None


def test_get_server_route_returns_404_for_missing_server() -> None:
    session: Any = _QueuedSession([_FakeResult(scalar_value=None)])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_server("server-id", user=user, session=session))

    assert exc_info.value.status_code == 404


def test_list_credentials_filters_by_server_and_owner() -> None:
    server = _make_server("00000000-0000-0000-0000-000000000001")
    credential = _make_credential(
        "00000000-0000-0000-0000-000000000002",
        server.id,
    )
    session: Any = _QueuedSession([
        _FakeResult(scalar_value=server),
        _FakeResult(items=[credential]),
    ])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    response = asyncio.run(ListCredentialsHandler(session).handle(server.id, user))

    assert response is not None
    assert response.total == 1
    assert response.items[0].cipher_text == base64.b64encode(b"cipher").decode("ascii")

    server_sql = str(session.executed_statements[0].compile(compile_kwargs={"literal_binds": True}))
    credential_sql = str(session.executed_statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "owner_user_id" in server_sql
    assert "owner_user_id" in credential_sql


def test_get_credential_returns_none_for_missing_resource() -> None:
    session: Any = _QueuedSession([_FakeResult(scalar_value=None)])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    result = asyncio.run(GetCredentialHandler(session).handle("credential-id", user))

    assert result is None


def test_get_credential_route_returns_404_for_missing_resource() -> None:
    session: Any = _QueuedSession([_FakeResult(scalar_value=None)])
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.VIEWER}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_credential("credential-id", user=user, session=session))

    assert exc_info.value.status_code == 404