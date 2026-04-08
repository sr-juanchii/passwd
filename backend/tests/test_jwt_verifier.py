from __future__ import annotations

import asyncio
from typing import Any

import pytest

import app.infrastructure.auth.jwt_verifier as jwt_module
from app.config.settings import Settings
from app.infrastructure.auth.jwt_verifier import JWTVerificationError, JWTVerifier


def test_jwt_verifier_fetches_and_caches_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    verifier = JWTVerifier(settings)
    counters = {"fetch": 0, "decode": 0}

    async def fake_fetch_jwks() -> None:
        counters["fetch"] += 1
        verifier._jwks_cache = {"kid-1": {"kid": "kid-1", "kty": "RSA"}}

    def fake_header(token: str) -> dict[str, str]:
        assert token == "signed-token"
        return {"kid": "kid-1", "alg": "RS256"}

    def fake_decode(
        token: str,
        key: Any,
        algorithms: list[str],
        audience: str,
        issuer: str,
        options: dict[str, bool],
    ) -> dict[str, Any]:
        counters["decode"] += 1
        assert token == "signed-token"
        assert key == {"kid": "kid-1", "kty": "RSA"}
        assert algorithms == ["RS256"]
        assert audience == settings.oidc_audience
        assert issuer == settings.oidc_issuer_url
        assert options["verify_exp"] is True
        return {
            "sub": "user-123",
            "preferred_username": "alice",
            "realm_roles": ["ADMIN", "EDITOR"],
        }

    monkeypatch.setattr(verifier, "_fetch_jwks", fake_fetch_jwks)
    monkeypatch.setattr(jwt_module.jwt, "get_unverified_header", fake_header)
    monkeypatch.setattr(jwt_module.jwt, "decode", fake_decode)

    first = asyncio.run(verifier.verify_token("signed-token"))
    second = asyncio.run(verifier.verify_token("signed-token"))

    assert counters["fetch"] == 1
    assert counters["decode"] == 2
    assert first == second
    assert first["sub"] == "user-123"
    assert first["realm_roles"] == ["ADMIN", "EDITOR"]


def test_jwt_verifier_rejects_unsupported_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = JWTVerifier(Settings())

    monkeypatch.setattr(
        jwt_module.jwt,
        "get_unverified_header",
        lambda token: {"kid": "kid-1", "alg": "HS256"},
    )

    with pytest.raises(JWTVerificationError, match="Unsupported signing algorithm"):
        asyncio.run(verifier.verify_token("signed-token"))