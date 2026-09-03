"""AIROS V3 - Auth0 token verification (Slice 5, DEC-011/DEC-014).

The API is a resource server: it accepts the Auth0 ID token (RS256 only -
DEC-014, same constraint as the Supabase integration) that the SPA already
holds, verifies signature against the tenant JWKS plus issuer, audience and
expiry, and exposes ONLY the verified claims downstream. Identity is never
taken from client-supplied fields (DEC-014) and the token is forwarded as-is
to PostgREST, so per-account RLS (DEC-013) stays the isolation boundary.
"""

from __future__ import annotations

import time

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWK

from .config import get_settings

JWKS_TTL_SECONDS = 3600.0
JWKS_HTTP_TIMEOUT = 10.0

# Module-level cache so tests can monkeypatch `get_jwks` / inspect state.
_JWKS_CACHE: dict = {"keys": None, "fetched_at": 0.0}


def fetch_jwks(url: str, timeout: float = JWKS_HTTP_TIMEOUT) -> dict:
    """Fetch the tenant JWKS (overridable/mocked in tests)."""
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_jwks(force: bool = False) -> dict:
    """Tenant JWKS with a simple TTL cache; force=True refetches (key rotation)."""
    settings = get_settings()
    now = time.time()
    stale = now - _JWKS_CACHE["fetched_at"] > JWKS_TTL_SECONDS
    if force or _JWKS_CACHE["keys"] is None or stale:
        _JWKS_CACHE["keys"] = fetch_jwks(settings.jwks_url)
        _JWKS_CACHE["fetched_at"] = now
    return _JWKS_CACHE["keys"]


class TokenError(ValueError):
    """A presented token is malformed, untrusted or does not match the tenant."""


def verify_token(token: str, jwks: dict | None = None) -> dict:
    """Verify an Auth0 ID token; return its claims or raise TokenError."""
    settings = get_settings()
    keys = jwks if jwks is not None else get_jwks()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError(f"malformed token: {exc}") from exc

    # DEC-014: RS256 only (HS256/PS256 are unsupported by Supabase third-party
    # auth; accepting them here would create a second, weaker trust path).
    if header.get("alg") != "RS256":
        raise TokenError("unsupported token algorithm (RS256 required)")

    kid = header.get("kid")
    jwk = next((k for k in keys.get("keys", []) if k.get("kid") == kid), None)
    if jwk is None and jwks is None:
        # Unknown kid -> the tenant may have rotated keys; refresh once.
        keys = get_jwks(force=True)
        jwk = next((k for k in keys.get("keys", []) if k.get("kid") == kid), None)
    if jwk is None:
        raise TokenError("token key (kid) is not in the tenant JWKS")

    public_key = PyJWK.from_dict(jwk).key
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.issuer,
            audience=settings.auth0_audience,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("token audience mismatch") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("token issuer mismatch") from exc
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid token: {exc}") from exc

    if not claims.get("sub"):
        raise TokenError("token carries no subject (sub)")
    return claims


def bearer_token(request: Request) -> str:
    """Extract the raw bearer token; 401 when absent/malformed."""
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) <= 7:
        raise HTTPException(
            status_code=401,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization[7:].strip()


def current_claims(token: str = Depends(bearer_token)) -> dict:
    """Dependency: verified Auth0 claims for the caller (401 on any failure)."""
    try:
        return verify_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
