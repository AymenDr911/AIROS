"""AIROS V3 - Auth0 token verification security tests (Slice 5, DEC-011/014).

Covers the failure paths that matter for a resource server: wrong algorithm,
unknown kid, bad signature, expired token, wrong issuer/audience, missing
credentials. All offline (forged RSA keypair + patched JWKS).
"""

from __future__ import annotations

import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import mint_token

# ---------------------------------------------------------------------------
# Unit level: verify_token()
# ---------------------------------------------------------------------------


def test_valid_token_returns_claims(api_env, rsa_material):
    from services.api.auth import verify_token
    from services.api.config import get_settings

    get_settings.cache_clear()
    try:
        _, jwks = rsa_material
        token = mint_token(rsa_material[0])
        claims = verify_token(token, jwks)
        assert claims["sub"] == "auth0|testuser"
        assert claims["email"] == "tester@airos.dev"
        assert claims["role"] == "authenticated"
    finally:
        get_settings.cache_clear()


def test_expired_token_rejected(api_env, rsa_material):
    from services.api.auth import TokenError, verify_token

    now = int(time.time())
    token = mint_token(rsa_material[0], claims_overrides={"iat": now - 3600, "exp": now - 60})
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expired token accepted")


def test_wrong_audience_rejected(api_env, rsa_material):
    from services.api.auth import TokenError, verify_token

    token = mint_token(rsa_material[0], claims_overrides={"aud": "someone-elses-app"})
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "audience" in str(exc)
    else:
        raise AssertionError("wrong-audience token accepted")


def test_wrong_issuer_rejected(api_env, rsa_material):
    from services.api.auth import TokenError, verify_token

    token = mint_token(rsa_material[0], claims_overrides={"iss": "https://evil.example.com/"})
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "issuer" in str(exc)
    else:
        raise AssertionError("wrong-issuer token accepted")


def test_hs256_token_rejected(api_env, rsa_material):
    # DEC-014: RS256 only - an HS256 token must never create a weaker path.
    from services.api.auth import TokenError, verify_token

    token = mint_token(rsa_material[0], alg="HS256", sign_with=b"symmetric-secret")
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "algorithm" in str(exc)
    else:
        raise AssertionError("HS256 token accepted")


def test_unknown_kid_rejected(api_env, rsa_material):
    from services.api.auth import TokenError, verify_token

    token = mint_token(rsa_material[0], kid="rotated-away")
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "kid" in str(exc)
    else:
        raise AssertionError("unknown-kid token accepted")


def test_bad_signature_rejected(api_env, rsa_material):
    # Signed by a DIFFERENT key than the one in the JWKS.
    from services.api.auth import TokenError, verify_token

    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    impostor_pem = impostor.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = mint_token(impostor_pem)
    try:
        verify_token(token, rsa_material[1])
    except TokenError:
        pass
    else:
        raise AssertionError("forged-signature token accepted")


def test_malformed_token_rejected():
    from services.api.auth import TokenError, verify_token

    try:
        verify_token("not-a-jwt", {"keys": []})
    except TokenError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("garbage accepted")


def test_missing_sub_rejected(api_env, rsa_material):
    from services.api.auth import TokenError, verify_token

    token = mint_token(rsa_material[0], claims_overrides={"sub": None})
    try:
        verify_token(token, rsa_material[1])
    except TokenError as exc:
        assert "sub" in str(exc)
    else:
        raise AssertionError("sub-less token accepted")


# ---------------------------------------------------------------------------
# HTTP level: 401 paths through the app
# ---------------------------------------------------------------------------


def test_missing_authorization_header_401(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_garbage_bearer_401(client):
    resp = client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_valid_token_passes_guard(client, rsa_material, monkeypatch):
    # fetch_account is stubbed (offline): what matters here is that the auth
    # guard ACCEPTS a genuinely signed token (no 401) and the endpoint runs.
    import services.api.routers.me as me_router

    monkeypatch.setattr(me_router, "fetch_account", lambda token, sub: None)
    token = mint_token(rsa_material[0])
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["account"] is None
