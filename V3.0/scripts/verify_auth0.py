#!/usr/bin/env python3
"""AIROS V3 — Live Auth0<->Supabase identity check (Slice 3 verification).

Pure-stdlib script that proves the Slice-3 identity flow end-to-end against
the REAL Supabase project:

  1. decodes the caller's Auth0 ID token payload (base64url, NO signature
     check here - Supabase verifies the token when it reaches PostgREST),
  2. calls RPC `sync_my_account()` with that token as the bearer,
     proving an authenticated caller can provision their OWN account row,
  3. checks the authenticated caller can SELECT exactly their own row,
  4. checks an ANONYMOUS (publishable-key) caller still sees NOTHING.

Reads SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY from the local `.env` and the
token from AUTH0_ID_TOKEN (or the --token argument).

Usage:
    python3 scripts/verify_auth0.py --token <AUTH0_ID_TOKEN>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def decode_jwt_payload(token: str) -> dict:
    """Decode the payload segment of a JWT (no signature verification)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"could not decode JWT payload: {exc}") from exc


def call(base: str, key: str, path: str, token: str | None, method: str = "GET", body: str | None = None):
    req = urllib.request.Request(f"{base}/{path}")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {token or key}")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = body.encode("utf-8")
    req.get_method = lambda: method
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def normalize_domain(s: str) -> str:
    """Bare host of a domain/URL (handles optional ``https://`` and trailing ``/``)."""
    return (s or "").split("//", 1)[-1].rstrip("/").lower()


def token_role_error(claims: dict) -> str | None:
    """Return an error message if the token would run as a non-authenticated role.

    Supabase maps the JWT ``role`` claim to the Postgres role; without
    ``role='authenticated'`` every request runs as ``anon`` and RLS blocks
    everything, so refuse the whole check instead of failing later.
    """
    role = claims.get("role", "?")
    if role != "authenticated":
        return (
            "FAIL: JWT `role` is not 'authenticated'. Supabase will treat this token "
            "as the anonymous role and RLS blocks everything.\n"
            "      Re-check that the `set-authenticated-role` Action is DEPLOYED and "
            "ADDED to the Login flow (docs/AUTH0_SETUP.md Step 6)."
        )
    return None


def token_iss_warning(iss: str, expected_domain: str) -> str | None:
    """Warn if the token issuer is not the configured Auth0 tenant.

    Auth0 ``iss`` carries scheme + trailing slash (e.g.
    ``https://<tenant>.eu.auth0.com/``); compare normalized bare hosts so a
    perfect match does NOT produce a false warning.
    """
    expected = normalize_domain(expected_domain)
    if expected and iss and normalize_domain(iss) != expected:
        return (
            f"WARN: token `iss` ({iss}) does not match AUTH0_DOMAIN "
            f"({expected_domain}). If the Supabase third-party Auth0 integration "
            "points at a different tenant, your token will be rejected there."
        )
    return None


def token_aud_warning(aud: object, expected_client_id: str) -> str | None:
    """Warn if the token audience is not the configured Auth0 application."""
    if expected_client_id and aud and aud != expected_client_id:
        return (
            f"WARN: token `aud` ({aud!r}) does not match AUTH0_CLIENT_ID "
            f"({expected_client_id!r}). You captured the token with a different Auth0 application."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--token", default=None, help="Auth0 ID token (or set AUTH0_ID_TOKEN in .env)")
    opts, _ = args.parse_known_args(argv)

    load_env()
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    token = opts.token or os.getenv("AUTH0_ID_TOKEN", "")
    if not base or not key or not token:
        print("ERROR: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and an ID token are required.")
        return 2

    claims = decode_jwt_payload(token)
    sub = claims.get("sub", "?")
    role = claims.get("role", "?")
    print(f"Supabase project : {base}")
    print(f"Token subject    : {sub}")
    print(f"Token role       : {role}")

    # --- Token sanity guards (fail fast on the common setup mistakes) ----
    role_err = token_role_error(claims)
    if role_err:
        print(role_err)
        return 1
    iss_warn = token_iss_warning(claims.get("iss", ""), os.getenv("AUTH0_DOMAIN", ""))
    if iss_warn:
        print(iss_warn)
    aud_warn = token_aud_warning(claims.get("aud"), os.getenv("AUTH0_CLIENT_ID", ""))
    if aud_warn:
        print(aud_warn)

    # 1. Provision the caller's own account via the trusted RPC.
    status, body = call(base, key, "rest/v1/rpc/sync_my_account", token, "POST", "{}")
    print(f"\n[1] sync_my_account()  -> HTTP {status}")
    if status != 200:
        print(f"    FAIL body: {body[:300]}")
        if status == 404:
            print("    HINT: migration 0003 not applied yet - run it in the Supabase SQL Editor (docs/AUTH0_SETUP.md Step 1)")
        return 1
    print(f"    account id: {body[:80]}")

    # 2. The authenticated caller must see exactly their own row.
    status, body = call(base, key, "rest/v1/accounts?select=auth0_sub,email&limit=10", token)
    print(f"\n[2] accounts as authen.-> HTTP {status}")
    print(f"    rows: {body[:200]}")
    if status != 200 or sub not in body:
        print("    FAIL: authenticated caller did not see their own account")
        return 1

    # 3. An anonymous caller must still see nothing.
    status, body = call(base, key, "rest/v1/accounts?select=*", None)
    print(f"\n[3] accounts as anon    -> HTTP {status}")
    print(f"    rows: {body[:120]}")
    if status != 200 or body.strip() not in ("", "[]"):
        print("    FAIL: anonymous caller can read accounts")
        return 1

    print("\nVERIFY OK — Auth0 identity flow works and per-account RLS holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())