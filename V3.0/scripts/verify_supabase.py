#!/usr/bin/env python3
"""AIROS V3 — Live Supabase smoke check (Slice 2 + Slice 3 verification).

Pure-stdlib script that verifies, against the REAL Supabase project:

  1. connectivity (the project is reachable),
  2. the four V3 tables exist,
  3. an anonymous (publishable-key) caller can read NOTHING on any
     user-data table (RLS lockdown on the `anon` role), which is the
     expected pre-Auth0 security posture,
  4. Slice-3 auth functions are present in the project AND NOT
     executable by the anonymous role (probing `sync_my_account()` with
     the publishable key): 401/403 = applied + anon blocked (good),
     404 = not applied, 400/200 = anon can execute (security leak — run
     migration 0004_auth_acl_hardening.sql), and
  5. the Auth0 tenant from `.env` (`AUTH0_DOMAIN`) is reachable.

Reads SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY from the local `.env`
(which is gitignored). No third-party dependency required.

Usage:
    python3 scripts/verify_supabase.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

TABLES = ("accounts", "profiles", "applications", "documents")


def load_env(path: Path = Path(".env")) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def rest_get(base: str, key: str, table: str) -> tuple[int, str]:
    url = f"{base}/rest/v1/{table}?select=*&limit=1"
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def rpc_probe(base: str, key: str) -> tuple[int, str]:
    """Probe whether `public.sync_my_account` exists (migration 0003 applied).

    The anonymous (publishable) key is used deliberately: the anon role has
    no EXECUTE grant on the function, but PostgREST distinguishes the two
    states cleanly — 404 PGRST202 means "function does NOT exist yet", while
    a 401/403 means "function EXISTS but anon is not allowed to call it".
    HTTP 200 here would be a security regression (anon can run it).
    """
    url = f"{base}/rest/v1/rpc/sync_my_account"
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.data = b"{}"
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def oidc_probe(domain: str) -> tuple[int, str]:
    """Check the Auth0 tenant responds on its public OpenID configuration."""
    url = f"https://{domain}/.well-known/openid-configuration"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except urllib.error.URLError as exc:  # DNS / TLS / connection
        return 0, str(exc.reason)


def main() -> int:
    load_env()
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not base or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY missing from .env")
        return 2

    ok = True
    not_applied = False
    table_states = []
    print(f"Supabase project : {base}")
    for table in TABLES:
        status, body = rest_get(base, key, table)
        existed = status == 200
        locked = existed and json.loads(body or "[]") == []
        if existed and not locked:
            ok = False
            state = f"UNEXPECTED ANON READ on {table}!"
        elif existed:
            state = f"{table}: table exists, RLS blocks anon"
        elif status in (404, 42501):
            not_applied = True
            state = f"{table}: not applied yet ({status})"
        else:
            ok = False
            state = f"{table}: unexpected status ({status})"
        table_states.append(state)
        print(f"  {state}")

    # --- Slice 3 (DEC-014): is migration 0003 (sync_my_account) applied? --
    # State machine, from the anonymous probe:
    #   404      -> function does not exist yet (migration 0003 not applied)
    #   401/403  -> function exists AND anon cannot execute (applied + safe)
    #   400/200  -> function exists AND ANON COULD EXECUTE it (security
    #               regression: Supabase default privileges directly granted
    #               EXECUTE to anon/service_role; run migration 0004)
    status, body = rpc_probe(base, key)
    sync_pending = False
    if status == 404:
        sync_state = "NOT APPLIED YET (run migration 0003 - see docs/AUTH0_SETUP.md Step 1)"
        sync_pending = True
    elif status in (401, 403):
        sync_state = f"APPLIED (function exists; anon probe rejected with HTTP {status})"
    elif status in (400, 200):
        sync_state = (
            f"APPLIED BUT ANON CAN EXECUTE (HTTP {status}: {body[:110]}...)\n"
            "    -> SECURITY FIX NEEDED: run migration 0004_auth_acl_hardening.sql"
            " in the Supabase SQL Editor (docs/AUTH0_SETUP.md Step 1, part 2)"
        )
        ok = False
    else:
        sync_state = f"unexpected probe result (HTTP {status} {body[:120]})"
        ok = False
    print(f"  sync_my_account : {sync_state}")

    # --- Slice 3 (DEC-014): Auth0 tenant reachable from .env? ------------
    domain = os.getenv("AUTH0_DOMAIN", "").strip()
    if domain:
        a_status, _ = oidc_probe(domain)
        if a_status == 200:
            print(f"  Auth0 tenant    : {domain} reachable (openid-configuration OK)")
        else:
            ok = False
            print(f"  Auth0 tenant    : {domain} probe failed (HTTP {a_status})")
    else:
        print("  Auth0 tenant    : not configured (add AUTH0_DOMAIN to .env)")

    # --- Aggregate result -------------------------------------------------
    if not ok:
        print("\nVERIFY FAILED")
        return 1
    if not_applied:
        print("\nVERIFY PENDING — project is live, but the base schema migrations are not applied yet.")
        return 3
    if sync_pending:
        print("\nVERIFY PENDING — Slice 3: migration 0003 (sync_my_account) not applied yet.")
        return 3
    print("\nVERIFY OK — project live, tables present, anon blocked by RLS + auth functions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())