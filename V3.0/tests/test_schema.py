"""AIROS V3 — Schema + RLS invariant tests (Slice 2).

Validates the V3 Postgres schema definition and per-account RLS policies
(DEC-013 / ISS-001/003/006) WITHOUT a live database: the DDL is parsed
structurally to prove the required safeguards are defined. Live
enforcement against Supabase is exercised later at the provisioning gate
(CHG-005).
"""

from __future__ import annotations

import re

import pytest

from database.schema import (
    CheckResult,
    load_migrations,
    policy_names,
    rls_events,
    table_columns,
    tables,
    validate_schema,
)

MIGRATIONS = load_migrations()
ALL_SQL = "\n".join(m.sql for m in MIGRATIONS)
DDL_SQL = "\n".join(line.split("--", 1)[0] for line in ALL_SQL.splitlines())


# ---------------------------------------------------------------------------
# Migration loading
# ---------------------------------------------------------------------------

def test_migrations_exist_and_are_ordered():
    assert MIGRATIONS, "no migrations found in database/migrations/"
    orders = [m.order for m in MIGRATIONS]
    assert orders == sorted(orders)
    assert orders[0] == 1  # schema DDL first


def test_schema_and_rls_files_present():
    names = [m.name for m in MIGRATIONS]
    assert "0001_schema.sql" in names
    assert "0002_rls.sql" in names


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def test_all_user_data_tables_defined():
    defined = tables(ALL_SQL)
    for t in ("accounts", "profiles", "applications", "documents"):
        assert t in defined, f"missing table: {t}"


def test_profiles_has_jsonb_plus_core_columns():
    cols = table_columns(ALL_SQL, "profiles")
    assert cols.get("account_id", "").upper().startswith("UUID")
    assert cols.get("skills", "").upper().startswith("JSONB")
    assert cols.get("experience", "").upper().startswith("JSONB")
    assert cols.get("strong_evidence", "").upper().startswith("BOOLEAN")


def test_applications_has_core_columns():
    cols = table_columns(ALL_SQL, "applications")
    for c in ("account_id", "application_id", "job_id", "company_id", "status", "timeline"):
        assert c in cols, f"missing column: {c}"
    assert cols["status"].upper().startswith("TEXT")


def test_documents_has_no_content_column():
    cols = table_columns(ALL_SQL, "documents")
    for banned in ("content", "content_base64", "base64", "data"):
        assert banned not in cols, f"documents must not carry content column: {banned}"
    assert "storage_ref" in cols  # pointer to the protected store (DEC-012)


# ---------------------------------------------------------------------------
# ISS-001 / ISS-006 legacy-hazard guards
# ---------------------------------------------------------------------------

def test_no_password_column_anywhere():
    assert "password" not in DDL_SQL.lower()


def test_no_inline_cv_content_anywhere():
    assert "content_base64" not in DDL_SQL.lower()
    assert "base64" not in DDL_SQL.lower()


# ---------------------------------------------------------------------------
# RLS structure (ISS-003)
# ---------------------------------------------------------------------------

def test_rls_enabled_and_forced_on_all_user_data_tables():
    events = rls_events(ALL_SQL)
    for t in ("accounts", "profiles", "applications", "documents"):
        assert events.get(t) == "force", f"{t} must ENABLE+FORCE RLS"


def test_no_rls_or_ddl_after_final_commit():
    # Every ALTER TABLE ... ROW LEVEL SECURITY and CREATE POLICY must sit
    # BEFORE the migration COMMIT so the transaction applies atomically.
    for mig in MIGRATIONS:
        commit_pos = mig.sql.rfind("COMMIT;")
        assert commit_pos != -1, f"{mig.name} has no COMMIT"
        after = mig.sql[commit_pos + len("COMMIT;") :].strip()
        # Trailing comments/whitespace are fine; any SQL payload is a bug.
        assert not after or not any(
            kw in after.split("--")[0] for kw in ("ALTER TABLE", "CREATE", "DROP", "INSERT", "UPDATE")
        ), f"{mig.name} has SQL after COMMIT: {after[:120]}"


def test_resolver_function_present():
    assert "current_account_id" in ALL_SQL
    assert "auth.jwt()" in ALL_SQL


def test_owner_scoped_tables_have_full_policy_coverage():
    for t in ("profiles", "applications", "documents"):
        for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            pat = rf"CREATE POLICY\s+\w+\s+ON\s+public\.{t}\s+FOR\s+{action}\b"
            assert re.search(pat, ALL_SQL, re.IGNORECASE | re.MULTILINE), f"missing {action} policy on {t}"


def test_accounts_are_not_client_creatable_or_deletable():
    # Accounts are created by the backend (Auth0 callback); clients must not
    # INSERT/DELETE their own accounts table row.
    insert_pat = re.compile(r"CREATE POLICY\s+\w+\s+ON\s+public.accounts\s+FOR\s+INSERT", re.IGNORECASE | re.MULTILINE)
    delete_pat = re.compile(r"CREATE POLICY\s+\w+\s+ON\s+public.accounts\s+FOR\s+DELETE", re.IGNORECASE | re.MULTILINE)
    assert not insert_pat.search(ALL_SQL)
    assert not delete_pat.search(ALL_SQL)


def test_no_hardcoded_secrets_in_migrations():
    # `service_role` as a bare role name in ACL DDL (0004) is legitimate;
    # what is banned is actual key material / URLs / connection strings.
    for banned in ("supabase.co", "postgresql://", "service_role_key", "sb_secret_", "sb_publishable_"):
        assert banned not in DDL_SQL.lower()


# ---------------------------------------------------------------------------
# validate_schema() aggregate
# ---------------------------------------------------------------------------

def test_validate_schema_all_green():
    results = validate_schema()
    assert results, "validate_schema() returned no checks"
    failed = [r for r in results if not r.ok]
    assert not failed, f"schema validation failed: {[(r.name, r.detail) for r in failed]}"
    # sanity on coverage: we assert many fine-grained checks above already
    assert len(results) >= 20


def test_validate_schema_reports_check_results():
    results = validate_schema()
    assert all(isinstance(r, CheckResult) for r in results)