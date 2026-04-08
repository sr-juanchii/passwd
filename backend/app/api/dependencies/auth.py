from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import Settings
from app.domain.identity import AuthenticatedUser, Role
from app.infrastructure.auth.jwt_verifier import JWTVerificationError, JWTVerifier

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)
_jwt_verifier: JWTVerifier | None = None


def init_jwt_verifier(settings: Settings) -> None:
    """Initialise the shared JWT verifier during application startup."""

    global _jwt_verifier  # noqa: PLW0603
    _jwt_verifier = JWTVerifier(settings)


def _get_verifier() -> JWTVerifier:
    if _jwt_verifier is None:
        raise RuntimeError("JWTVerifier not initialized")
    return _jwt_verifier


def _extract_roles(payload: dict[str, Any]) -> list[str]:
    raw_roles = payload.get("realm_roles")
    if isinstance(raw_roles, str):
        return [raw_roles]
    if isinstance(raw_roles, (list, tuple, set, frozenset)):
        return [str(role) for role in raw_roles]

    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        nested_roles = realm_access.get("roles")
        if isinstance(nested_roles, str):
            return [nested_roles]
        if isinstance(nested_roles, (list, tuple, set, frozenset)):
            return [str(role) for role in nested_roles]

    return []


def _coerce_role(value: Any) -> Role | None:
    if not isinstance(value, str):
        return None

    try:
        return Role(value)
    except ValueError:
        return None


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials,
        Depends(_bearer_scheme),
    ],
    verifier: Annotated[JWTVerifier, Depends(_get_verifier)],
) -> AuthenticatedUser:
    """Validate the access token and return the authenticated user identity."""

    try:
        payload = await verifier.verify_token(credentials.credentials)
    except JWTVerificationError as exc:
        logger.warning("Authentication failed", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        logger.warning("Authentication failed", extra={"reason": "missing sub"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_roles = _extract_roles(payload)
    valid_roles: frozenset[Role] = frozenset(
        role
        for role in (_coerce_role(raw_role) for raw_role in raw_roles)
        if role is not None
    )
    if not valid_roles:
        logger.warning("User has no valid roles", extra={"sub": sub})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No valid roles assigned",
        )

    username_value = payload.get("preferred_username")
    username = username_value if isinstance(username_value, str) and username_value else sub

    user = AuthenticatedUser(sub=sub, username=username, roles=valid_roles)
    logger.info(
        "User authenticated",
        extra={
            "user_id": user.sub,
            "roles": [role.value for role in sorted(user.roles, key=lambda role: role.value)],
        },
    )

    return user


class RoleRequired:
    """Dependency that enforces one or more accepted roles."""

    def __init__(self, *allowed_roles: Role) -> None:
        if not allowed_roles:
            raise ValueError("At least one role must be provided")
        self._allowed = frozenset(allowed_roles)

    async def __call__(
        self,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not user.has_any_role(*self._allowed):
            logger.warning(
                "Authorization denied",
                extra={
                    "user_id": user.sub,
                    "required_roles": [
                        role.value for role in sorted(self._allowed, key=lambda role: role.value)
                    ],
                    "user_roles": [
                        role.value for role in sorted(user.roles, key=lambda role: role.value)
                    ],
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return user


RequireAdmin = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN)),
]
RequireEditor = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN, Role.EDITOR)),
]
RequireViewer = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN, Role.EDITOR, Role.VIEWER)),
]