"""GET /api/me - verified identity + the caller's OWN RLS-scoped account row.

Read-only by design (Slice 5): writes belong to later service slices. The
caller's Auth0 ID token is forwarded to Supabase PostgREST unchanged, so
authorization is exactly the live-verified RLS path (DEC-013/DEC-014) - the
API holds NO service_role key and never impersonates the user beyond what
their own token grants.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth import bearer_token, current_claims
from ..config import get_settings

router = APIRouter(prefix="/api")

ACCOUNT_COLUMNS = "id,email,auth0_sub,verified,created_at,updated_at,source_key"


def fetch_account(token: str, sub: str) -> dict | None:
    """PostgREST SELECT on `accounts` as the caller (mocked in tests)."""
    settings = get_settings()
    resp = httpx.get(
        f"{settings.supabase_url}/rest/v1/accounts",
        params={"select": ACCOUNT_COLUMNS, "auth0_sub": f"eq.{sub}"},
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=15.0,
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"upstream PostgREST error: HTTP {resp.status_code}",
        )
    rows = resp.json()
    return rows[0] if rows else None


@router.get("/me")
def me(
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    """Verified claims + the caller's own account row (or provision hint)."""
    sub = str(claims["sub"])
    account = fetch_account(token, sub)
    return {
        "sub": sub,
        "email": claims.get("email"),
        "role": claims.get("role"),
        "account": account,
        "provision_hint": (
            None if account else "call sync_my_account() to provision your account row"
        ),
    }
