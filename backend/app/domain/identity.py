from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique


@unique
class Role(StrEnum):
    """Roles realm alineados con el IdP."""

    ADMIN = "ADMIN"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identidad inmutable derivada de un JWT verificado."""

    sub: str
    username: str
    roles: frozenset[Role]

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_any_role(self, *roles: Role) -> bool:
        return any(role in self.roles for role in roles)

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)