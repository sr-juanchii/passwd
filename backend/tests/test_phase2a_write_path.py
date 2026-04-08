from __future__ import annotations

import asyncio
import base64
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

import app.application.commands.credential_commands as credential_commands_module
import app.application.commands.server_commands as server_commands_module
from app.application.commands.credential_commands import CreateCredentialHandler
from app.application.commands.schemas import CreateCredentialCommand, CreateServerCommand, UpdateServerCommand
from app.application.commands.server_commands import CreateServerHandler, DeleteServerHandler, UpdateServerHandler
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser, Role
from app.main import app


@dataclass
class _FakeResult:
    rowcount: int = 0
    entity: Any | None = None

    def scalar_one_or_none(self) -> Any | None:
        return self.entity


class _FakeSession:
    def __init__(self, result: _FakeResult | None = None) -> None:
        self.result = result or _FakeResult()
        self.added: list[Any] = []
        self.executed_statements: list[Any] = []
        self.commits = 0

    def add(self, entity: Any) -> None:
        self.added.append(entity)

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed_statements.append(statement)
        return self.result

    async def commit(self) -> None:
        self.commits += 1


def test_api_v1_routes_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/servers/" in paths
    assert "/api/v1/servers/{server_id}" in paths
    assert "/api/v1/credentials/" in paths
    assert "/api/v1/credentials/{server_id}" not in paths


def test_create_server_command_validates_and_normalizes_hostname() -> None:
    command = CreateServerCommand(
        hostname="Web-Server-01",
        ip_address="192.168.1.10",
        operating_system="Ubuntu 22.04 LTS",
    )

    assert command.hostname == "web-server-01"


def test_create_credential_command_decodes_base64_payload() -> None:
    command = CreateCredentialCommand(
        server_id=str(uuid.uuid4()),
        credential_username="root",
        cipher_text=base64.b64encode(b"cipher").decode("ascii"),
        wrapped_dek=base64.b64encode(b"wrapped").decode("ascii"),
        iv=base64.b64encode(b"iv-bytes-1234").decode("ascii"),
        auth_tag=base64.b64encode(b"auth-tag-12345678").decode("ascii"),
        pbkdf2_salt=base64.b64encode(b"salt-bytes-1234567890123456").decode("ascii"),
        pbkdf2_iterations=600000,
    )

    assert command.cipher_text_bytes == b"cipher"
    assert command.wrapped_dek_bytes == b"wrapped"
    assert command.iv_bytes == b"iv-bytes-1234"
    assert command.auth_tag_bytes == b"auth-tag-12345678"
    assert command.pbkdf2_salt_bytes == b"salt-bytes-1234567890123456"


def test_create_server_handler_assigns_owner_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = _FakeSession()
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.ADMIN}),
    )
    command = CreateServerCommand(
        hostname="web-server",
        ip_address="10.0.0.10",
        operating_system="Ubuntu 22.04",
    )

    monkeypatch.setattr(server_commands_module.uuid, "uuid4", lambda: uuid.UUID(int=1))

    server_id = asyncio.run(CreateServerHandler(fake_session).handle(command, user))

    assert server_id == str(uuid.UUID(int=1))
    assert fake_session.commits == 1
    assert len(fake_session.added) == 1
    entity = fake_session.added[0]
    assert isinstance(entity, ServerEntity)
    assert entity.owner_user_id == user.sub
    assert entity.hostname == "web-server"


def test_update_server_handler_scopes_non_admin_statement() -> None:
    fake_session = _FakeSession(_FakeResult(rowcount=1))
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.EDITOR}),
    )
    command = UpdateServerCommand(hostname="web-server-02")

    updated = asyncio.run(UpdateServerHandler(fake_session).handle("server-1", command, user))

    assert updated is True
    assert fake_session.commits == 1
    assert len(fake_session.executed_statements) == 1
    assert "owner_user_id" in str(fake_session.executed_statements[0])


def test_delete_server_handler_scopes_non_admin_statement() -> None:
    fake_session = _FakeSession(_FakeResult(rowcount=1))
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.EDITOR}),
    )

    deleted = asyncio.run(DeleteServerHandler(fake_session).handle("server-1", user))

    assert deleted is True
    assert fake_session.commits == 1
    assert len(fake_session.executed_statements) == 1
    assert "owner_user_id" in str(fake_session.executed_statements[0])


def test_create_credential_handler_stores_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    server_id = str(uuid.UUID(int=3))
    server = ServerEntity(
        id=server_id,
        hostname="web-server",
        ip_address="10.0.0.10",
        operating_system="Ubuntu 22.04",
        owner_user_id="user-123",
    )
    fake_session = _FakeSession(_FakeResult(entity=server))
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.EDITOR}),
    )
    command = CreateCredentialCommand(
        server_id=server.id,
        credential_username="root",
        cipher_text=base64.b64encode(b"cipher").decode("ascii"),
        wrapped_dek=base64.b64encode(b"wrapped").decode("ascii"),
        iv=base64.b64encode(b"iv-bytes-1234").decode("ascii"),
        auth_tag=base64.b64encode(b"auth-tag-12345678").decode("ascii"),
        pbkdf2_salt=base64.b64encode(b"salt-bytes-1234567890123456").decode("ascii"),
        pbkdf2_iterations=600000,
    )

    monkeypatch.setattr(credential_commands_module.uuid, "uuid4", lambda: uuid.UUID(int=2))

    credential_id = asyncio.run(CreateCredentialHandler(fake_session).handle(command, user))

    assert credential_id == str(uuid.UUID(int=2))
    assert fake_session.commits == 1
    assert len(fake_session.added) == 1
    entity = fake_session.added[0]
    assert entity.owner_user_id == user.sub
    assert entity.cipher_text == b"cipher"
    assert entity.wrapped_dek == b"wrapped"
    assert entity.iv == b"iv-bytes-1234"


def test_create_credential_handler_denies_missing_server() -> None:
    fake_session = _FakeSession(_FakeResult(entity=None))
    user = AuthenticatedUser(
        sub="user-123",
        username="alice",
        roles=frozenset({Role.EDITOR}),
    )
    command = CreateCredentialCommand(
        server_id=str(uuid.uuid4()),
        credential_username="root",
        cipher_text=base64.b64encode(b"cipher").decode("ascii"),
        wrapped_dek=base64.b64encode(b"wrapped").decode("ascii"),
        iv=base64.b64encode(b"iv-bytes-1234").decode("ascii"),
        auth_tag=base64.b64encode(b"auth-tag-12345678").decode("ascii"),
        pbkdf2_salt=base64.b64encode(b"salt-bytes-1234567890123456").decode("ascii"),
        pbkdf2_iterations=600000,
    )

    with pytest.raises(PermissionError):
        asyncio.run(CreateCredentialHandler(fake_session).handle(command, user))