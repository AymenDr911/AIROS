"""Shared fixtures for the Slice-5 API tests (offline, DB-free).

Strategy (mirrors the existing suite philosophy: pure, no external services):
- forge an RSA keypair and mint real RS256 tokens signed with it,
- monkeypatch the JWKS fetch to return the matching public key,
- drive the app through FastAPI's TestClient (httpx ASGI transport).
"""

from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

KID = "test-key"
DOMAIN = "test-tenant.eu.auth0.com"
CLIENT_ID = "test-client-id"
ISSUER = f"https://{DOMAIN}/"


def _b64url_int(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="session")
def rsa_material() -> tuple[bytes, dict]:
    """(private PEM, matching JWKS dict) for minting/verifying test tokens."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_int(pub.n),
                "e": _b64url_int(pub.e),
            }
        ]
    }
    return private_pem, jwks


def mint_token(
    private_pem: bytes,
    *,
    kid: str = KID,
    alg: str = "RS256",
    claims_overrides: dict | None = None,
    sign_with: bytes | None = None,
) -> str:
    """Mint a token the way Auth0 would (RS256, kid header).

    A None override REMOVES the claim (e.g. mint a token with no `sub`).
    """
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "auth0|testuser",
        "email": "tester@airos.dev",
        "role": "authenticated",
        "iat": now,
        "exp": now + 600,
    }
    for key, value in (claims_overrides or {}).items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    return jwt.encode(
        claims,
        sign_with if sign_with is not None else private_pem,
        algorithm=alg,
        headers={"kid": kid},
    )


@pytest.fixture()
def api_env(monkeypatch):
    """Deterministic env + cleared settings cache for the app under test.

    `load_env` is disabled so the developer's real .env can never leak into
    the test results (isolation, not just env pre-seeding).
    """
    monkeypatch.setattr("services.api.config.load_env", lambda path=None: None)
    monkeypatch.setenv("AUTH0_DOMAIN", DOMAIN)
    monkeypatch.setenv("AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.setenv("AIROS_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("AIROS_ENV", "test")
    from services.api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(api_env, rsa_material, monkeypatch):
    """TestClient with the JWKS patched to the forged test key."""
    _, jwks = rsa_material
    import services.api.auth as auth

    monkeypatch.setattr(auth, "get_jwks", lambda force=False: jwks)
    from services.api.main import create_app

    return TestClient(create_app())
