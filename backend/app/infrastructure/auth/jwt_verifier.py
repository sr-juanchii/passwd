from __future__ import annotations

import logging
from typing import Any

import httpx
from jose import JWTError, jwt  # type: ignore[import-untyped]

from app.config.settings import Settings

logger = logging.getLogger(__name__)


class JWTVerificationError(Exception):
    """Raised when a JWT cannot be validated."""


class JWTVerifier:
    """Validate RS256 JWTs against a cached JWKS document with TTL-based refresh."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer_url.rstrip("/")
        self._audience = settings.oidc_audience
        self._jwks_url = settings.oidc_jwks_url or (
            f"{self._issuer}/protocol/openid-connect/certs"
        )
        self._jwks_cache: dict[str, dict[str, Any]] = {}
        self._jwks_fetched: bool = False

    async def _fetch_jwks(self) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            ) as client:
                response = await client.get(self._jwks_url)
                response.raise_for_status()
                jwks_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JWTVerificationError(f"Unable to fetch JWKS: {exc}") from exc

        keys = jwks_payload.get("keys", []) if isinstance(jwks_payload, dict) else []
        cache: dict[str, dict[str, Any]] = {}
        for key in keys:
            if not isinstance(key, dict):
                continue
            kid = key.get("kid")
            if isinstance(kid, str) and kid:
                cache[kid] = key

        if not cache:
            raise JWTVerificationError("JWKS document did not contain usable signing keys")

        self._jwks_cache = cache
        self._jwks_fetched = True
        logger.info(
            "JWKS refreshed",
            extra={"key_count": len(self._jwks_cache), "jwks_url": self._jwks_url},
        )

    async def verify_token(self, token: str) -> dict[str, Any]:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise JWTVerificationError(f"Invalid token header: {exc}") from exc

        kid = unverified_header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise JWTVerificationError("Token header missing 'kid'")

        algorithm = unverified_header.get("alg")
        if algorithm != "RS256":
            raise JWTVerificationError(f"Unsupported signing algorithm: {algorithm!r}")

        if kid not in self._jwks_cache:
            await self._fetch_jwks()

        signing_key = self._jwks_cache.get(kid)
        if signing_key is None:
            raise JWTVerificationError(f"Unknown signing key: {kid}")

        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                },
            )
        except JWTError as exc:
            raise JWTVerificationError(f"Token verification failed: {exc}") from exc

        return payload