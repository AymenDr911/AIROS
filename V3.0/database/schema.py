"""AIROS V3 — Schema definition loader + invariant validator (Slice 2).

Pure, dependency-free parsing of the SQL migration files under
``database/migrations/``. It exposes:

- :func:`load_migrations` — ordered migrations for provisioning/debugging
- :func:`tables`, :func:`table_columns`, :func:`rls_events`,
  :func:`policy_names` — lightweight extraction used by the validator
- :func:`validate_schema` — the *security invariants* that must hold
  before the V3 schema is considered safe (DEC-013 / ISS-001/003/006)

No PostgreSQL client is required; a live database applies the DDL through
the Supabase SQL editor or backend migrations (CHG-005).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

USER_DATA_TABLES = ("accounts", "profiles", "applications", "documents")
OWNER_SCOPED_TABLES = ("profiles", "applications", "documents")  # scoped by account_id


@dataclass(frozen=True)
class Migration:
    """A single ordered migration file."""

    name: str
    sql: str

    @property
    def order(self) -> int:
        return int(re.match(r"(\d+)_", self.name).group(1))


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one security-invariant check."""

    name: str
    ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


def load_migrations(directory: Optional[Path] = None) -> List[Migration]:
    """Load ``*.sql`` migrations in lexicographic (execution) order."""
    d = Path(directory or MIGRATIONS_DIR)
    files = sorted(p for p in d.glob("*.sql") if p.is_file())
    return [Migration(name=p.name, sql=p.read_text(encoding="utf-8")) for p in files]


def _findall(pattern: str, sql: str) -> List[str]:
    return re.findall(pattern, sql, flags=re.IGNORECASE | re.MULTILINE)


def _strip_comments(sql: str) -> str:
    """Remove ``--`` line comments so token scans hit DDL, not prose."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def tables(sql: str) -> Set[str]:
    """Names of tables created in the given migration SQL."""
    return set(_findall(r"CREATE TABLE IF NOT EXISTS\s+public\.(\w+)", sql)) | set(
        _findall(r"CREATE TABLE\s+public\.(\w+)", sql)
    )


def table_columns(sql: str, table: str) -> Dict[str, str]:
    """Column name -> data type, parsed from a ``CREATE TABLE`` block."""
    m = re.search(
        rf"CREATE TABLE IF NOT EXISTS\s+public\.{table}\s*\((.*?)\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(
            rf"CREATE TABLE\s+public\.{table}\s*\((.*?)\);",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if not m:
        return {}
    cols: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        parts = line.split()
        if len(parts) >= 2 and parts[0].isidentifier() and re.match(r"^[A-Za-z]+", parts[1]):
            cols[parts[0].lower()] = " ".join(parts[1:])
    return cols


def rls_events(sql: str) -> Dict[str, str]:
    """table -> 'enable'|'force'|'both' for ALTER TABLE ... ROW LEVEL SECURITY."""
    events: Dict[str, str] = {}
    for m in re.finditer(
        r"ALTER TABLE\s+public\.(\w+)\s+(ENABLE|FORCE)\s+ROW LEVEL SECURITY",
        sql,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        tbl, kind = m.group(1).lower(), m.group(2).lower()
        prev = events.get(tbl, "")
        events[tbl] = kind if kind == "force" else (prev or kind)
    return events


def policy_names(sql: str) -> List[str]:
    """Names of all CREATE POLICY statements in the migration SQL."""
    return [m.strip() for m in _findall(r"CREATE POLICY\s+(\w+)", sql)]


def _migration_named(name: str) -> Optional[str]:
    """Return the SQL text of the migration with the given filename, if any."""
    for m in load_migrations():
        if m.name == name:
            return m.sql
    return None


def _has_policy(sql: str, table: str, action: str) -> bool:
    pat = rf"CREATE POLICY\s+\w+\s+ON\s+public\.{table}\s+FOR\s+{action}\b"
    return bool(re.search(pat, sql, flags=re.IGNORECASE | re.MULTILINE))


def validate_schema() -> List[CheckResult]:
    """Run every security invariant against the migration definitions.

    Pure and database-independent: it proves the DDL *defines* the
    required safeguards; live enforcement still needs the migrations
    applied to the Supabase project (CHG-005 gate).
    """
    migs = load_migrations()
    all_sql = "\n".join(m.sql for m in migs)
    ddl = _strip_comments(all_sql)
    results: List[CheckResult] = []

    # 0. Migrations present in order.
    results.append(CheckResult("migrations loaded", bool(migs), ", ".join(m.name for m in migs)))
    orders = [m.order for m in migs]
    results.append(CheckResult("migrations ordered", orders == sorted(orders), str(orders)))

    # 1. All expected user-data tables are defined.
    defined_tables = tables(all_sql)
    missing = [t for t in USER_DATA_TABLES if t not in defined_tables]
    results.append(
        CheckResult(
            "user-data tables defined",
            not missing,
            f"defined={sorted(defined_tables)} missing={missing}",
        )
    )

    # 2. No V2 password column anywhere (ISS-001).
    results.append(CheckResult("no password column (ISS-001)", "password" not in ddl.lower()))

    # 3. No inline base64 / document content in the DB (ISS-006).
    leaked = [k for k in ("content_base64", "base64") if k in ddl.lower()]
    results.append(CheckResult("no inline document content (ISS-006)", not leaked, str(leaked)))

    # 4. Every owner-scoped table carries account_id + cascade to accounts.
    for tbl in OWNER_SCOPED_TABLES:
        cols = table_columns(all_sql, tbl)
        has_account_id = "account_id" in cols
        has_cascade = bool(
            re.search(r"REFERENCES public\.accounts\(id\) ON DELETE CASCADE", all_sql, re.IGNORECASE)
        )
        results.append(
            CheckResult(
                f"{tbl} owns account_id+cascade",
                has_account_id and has_cascade,
                f"account_id={has_account_id} cascade={has_cascade}",
            )
        )

    # 5. RLS enabled AND forced on every user-data table.
    ev = rls_events(all_sql)
    for tbl in USER_DATA_TABLES:
        kind = ev.get(tbl, "")
        results.append(CheckResult(f"rls {tbl} enabled+forced", kind == "force", kind or "missing"))

    # 6. current_account_id() resolves Auth0 sub (DEC-003/DEC-013).
    has_resolver = "current_account_id" in all_sql and "auth.jwt()" in all_sql
    results.append(CheckResult("current_account_id resolver", has_resolver))

    # 7. Full per-account policy coverage on owner-scoped tables.
    for tbl in OWNER_SCOPED_TABLES:
        for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            ok = _has_policy(all_sql, tbl, action)
            results.append(CheckResult(f"policy {tbl} {action}", ok))

    # 8. accounts: no insert/delete exposure to clients; own-row select/update only.
    results.append(
        CheckResult(
            "accounts own-row policies only",
            _has_policy(all_sql, "accounts", "SELECT")
            and _has_policy(all_sql, "accounts", "UPDATE")
            and not _has_policy(all_sql, "accounts", "INSERT")
            and not _has_policy(all_sql, "accounts", "DELETE"),
        )
    )

    # 9. No secrets/connection strings hardcoded in migrations. Note: the
    # word `service_role` AS A POSTGRES ROLE NAME is legitimate (0004
    # revokes EXECUTE from the service_role role) - what must never appear
    # is actual key material or a URL/connection prefix, i.e. `service_role`
    # followed by a key value, a `sb_*` secret, a project URL or a DSN.
    secret_markers = ("supabase.co", "postgresql://", "service_role_key", "sb_secret_", "sb_publishable_")
    secrets = [k for k in secret_markers if k in ddl.lower()]
    results.append(CheckResult("no secrets in migrations", not secrets, str(secrets)))

    # 10. Auth0 integration (DEC-014): sync_my_account() must exist, be
    # SECURITY DEFINER, read `sub` only from the verified JWT, and be
    # callable only by `authenticated` (never anon/public).
    ddl_lower = ddl.lower()
    has_sync = "create or replace function public.sync_my_account()" in ddl_lower
    results.append(CheckResult("auth sync_my_account defined", has_sync))
    results.append(CheckResult("auth sync is SECURITY DEFINER", has_sync and "security definer" in ddl_lower))
    results.append(CheckResult("auth sync reads sub from JWT only", has_sync and "auth.jwt() ->> 'sub'" in ddl_lower))
    grants_ok = "grant execute on function public.sync_my_account() to authenticated" in ddl_lower
    revokes_ok = "revoke all on function public.sync_my_account() from public" in ddl_lower
    results.append(CheckResult("auth sync grants+revokes", has_sync and grants_ok and revokes_ok))

    # 10b. Auth ACL hardening (0004): Supabase default privileges directly
    # grant EXECUTE on new `public` functions to `anon`/`service_role`; a
    # `REVOKE FROM PUBLIC` alone (0003) does NOT cancel those direct grants,
    # so 0004 must revoke them EXPLICITLY (discovered on the live project).
    mig_4 = _migration_named("0004_auth_acl_hardening.sql")
    has_04 = mig_4 is not None
    results.append(CheckResult("auth ACL hardening migration present", has_04))
    results.append(
        CheckResult(
            "auth funcs revoked from anon+service_role",
            has_04
            and "revoke all on function public.sync_my_account() from anon" in (mig_4 or "").lower()
            and "revoke all on function public.sync_my_account() from service_role" in (mig_4 or "").lower()
            and "revoke all on function public.current_account_id() from anon" in (mig_4 or "").lower()
            and "revoke all on function public.current_account_id() from service_role" in (mig_4 or "").lower(),
        )
    )
    results.append(
        CheckResult(
            "auth default privileges revoked",
            has_04
            and "alter default privileges in schema public" in (mig_4 or "").lower()
            and "revoke execute on functions from public, anon, service_role" in (mig_4 or "").lower(),
        )
    )

    # 11. Accounts are still not client-insertable/deletable: a new account
    # can ONLY be created through the trusted sync_my_account() function.
    results.append(CheckResult("accounts still no client insert", not _has_policy(ddl, "accounts", "INSERT")))
    results.append(CheckResult("accounts still no client delete", not _has_policy(ddl, "accounts", "DELETE")))

    return results