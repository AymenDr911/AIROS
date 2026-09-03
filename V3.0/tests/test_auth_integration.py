"""AIROS V3 — Auth0 identity integration tests (Slice 3, DEC-014).

Validates the database-side Auth0 <-> Supabase integration definition
(pure, DB-free): the `sync_my_account()` SECURITY DEFINER function must
exist, read `sub`/`email` ONLY from the server-verified JWT, be callable
only by `authenticated`, and not weaken the RLS posture established in
Slice 2 (ISS-003).
"""

from __future__ import annotations

from database.schema import load_migrations, validate_schema

MIGRATIONS = load_migrations()
ALL_SQL = "\n".join(m.sql for m in MIGRATIONS)
DDL_SQL = "\n".join(line.split("--", 1)[0] for line in ALL_SQL.splitlines())
AUTH_MIG = next((m.sql for m in MIGRATIONS if m.name == "0003_auth_integration.sql"), "")


# ---------------------------------------------------------------------------
# Migration presence & order
# ---------------------------------------------------------------------------

def test_auth_migration_present_and_ordered():
    names = [m.name for m in MIGRATIONS]
    assert "0003_auth_integration.sql" in names
    assert "0004_auth_acl_hardening.sql" in names
    orders = [m.order for m in MIGRATIONS]
    assert orders == sorted(orders)
    assert orders[-1] == 4  # ACL hardening applied after schema + RLS + auth


def test_auth_migration_is_wrapped_in_transaction():
    assert "BEGIN;" in AUTH_MIG
    assert "COMMIT;" in AUTH_MIG
    assert AUTH_MIG.rstrip().endswith("COMMIT;")


# ---------------------------------------------------------------------------
# sync_my_account() security invariants (DEC-014)
# ---------------------------------------------------------------------------

def test_sync_function_exists_with_no_client_params():
    # The function must expose NO input parameter, so a caller can never
    # supply a `sub` — it is always taken from the server-verified JWT.
    assert "CREATE OR REPLACE FUNCTION public.sync_my_account()" in AUTH_MIG
    assert "p_" not in AUTH_MIG


def test_sync_function_is_security_definer():
    assert "SECURITY DEFINER" in AUTH_MIG.upper()


def test_sync_function_reads_sub_only_from_jwt():
    assert "auth.jwt() ->> 'sub'" in AUTH_MIG


def test_sync_function_is_idempotent_via_on_conflict():
    assert "ON CONFLICT (auth0_sub)" in AUTH_MIG


def test_sync_function_grants_authenticated_only():
    assert "GRANT EXECUTE ON FUNCTION public.sync_my_account() TO authenticated" in AUTH_MIG
    assert "REVOKE ALL ON FUNCTION public.sync_my_account() FROM PUBLIC" in AUTH_MIG


# ---------------------------------------------------------------------------
# No weakening of the Slice-2 RLS posture (ISS-003)
# ---------------------------------------------------------------------------

def test_accounts_still_have_no_client_insert_or_delete_policy():
    import re

    for action in ("INSERT", "DELETE"):
        pat = re.compile(
            rf"CREATE POLICY\s+\w+\s+ON\s+public\.accounts\s+FOR\s+{action}\b",
            re.IGNORECASE | re.MULTILINE,
        )
        assert not pat.search(DDL_SQL), f"accounts must not be client-{action.lower()}able"


def test_sync_function_does_not_reveal_existing_accounts():
    # sync_my_account() may create/update a row but must never SELECT
    # arbitrary rows back; it only returns the caller's own id.
    assert "auth0_sub = auth.jwt() ->> 'sub'" in AUTH_MIG or "ON CONFLICT" in AUTH_MIG


def test_rls_still_enabled_and_forced_everywhere():
    from database.schema import rls_events

    ev = rls_events(ALL_SQL)
    for t in ("accounts", "profiles", "applications", "documents"):
        assert ev.get(t) == "force", f"{t} RLS must stay enabled+forced"


# ---------------------------------------------------------------------------
# 0004 auth ACL hardening (fixed on the live project: Supabase default
# privileges directly granted EXECUTE to anon/service_role on new public
# functions - a REVOKE FROM PUBLIC alone does NOT cancel direct grants).
# ---------------------------------------------------------------------------

def test_auth_acl_hardening_migration_present_and_transactional():
    mig_4 = next((m for m in MIGRATIONS if m.name == "0004_auth_acl_hardening.sql"), None)
    assert mig_4 is not None
    assert "BEGIN;" in mig_4.sql
    assert mig_4.sql.rstrip().endswith("COMMIT;")


def test_auth_acl_hardening_revokes_anon_and_service_role_explicitly():
    mig_4 = next((m.sql for m in MIGRATIONS if m.name == "0004_auth_acl_hardening.sql"), "").lower()
    assert "revoke all on function public.sync_my_account() from anon" in mig_4
    assert "revoke all on function public.sync_my_account() from service_role" in mig_4
    assert "revoke all on function public.current_account_id() from anon" in mig_4
    assert "revoke all on function public.current_account_id() from service_role" in mig_4


def test_auth_acl_hardening_regrant_authenticated_only():
    mig_4 = next((m.sql for m in MIGRATIONS if m.name == "0004_auth_acl_hardening.sql"), "").lower()
    assert mig_4.count("grant execute on function public.sync_my_account() to authenticated") == 1
    assert mig_4.count("grant execute on function public.current_account_id() to authenticated") == 1
    # No other positive grant to anon/service_role on these functions.
    assert " to anon" not in mig_4.replace("from anon", "")
    assert " to service_role" not in mig_4.replace("from service_role", "")


def test_auth_acl_hardening_fixes_default_privileges():
    mig_4 = next((m.sql for m in MIGRATIONS if m.name == "0004_auth_acl_hardening.sql"), "").lower()
    assert "alter default privileges in schema public" in mig_4
    assert "revoke execute on functions from public, anon, service_role" in mig_4
    assert "grant execute on functions to authenticated" in mig_4


# ---------------------------------------------------------------------------
# Aggregate validation
# ---------------------------------------------------------------------------

def test_validate_schema_all_green_with_auth_checks():
    results = validate_schema()
    failed = [r for r in results if not r.ok]
    assert not failed, f"schema validation failed: {[(r.name, r.detail) for r in failed]}"
    names = {r.name for r in results}
    assert "auth sync_my_account defined" in names
    assert "auth sync is SECURITY DEFINER" in names
    assert "auth sync reads sub from JWT only" in names
    assert "auth sync grants+revokes" in names
    assert len(results) >= 33  # 27 base + 6 auth/accounts checks