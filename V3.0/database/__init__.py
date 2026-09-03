"""AIROS V3 — database layer (Slice 2).

Owns the *definition* and *validation* of the V3 Postgres schema + RLS
without requiring a live database, so the security invariants (DEC-013 /
ISS-001/003/006) are testable on any machine (free-plan constraint).

Migrations live in ``database/migrations/*.sql`` and are executed in
lexicographic order against the Supabase project during provisioning
(CHG-005 gate).
"""

from __future__ import annotations

from .schema import (
    Migration,
    load_migrations,
    tables,
    table_columns,
    rls_events,
    policy_names,
    validate_schema,
    CheckResult,
)

__all__ = [
    "Migration",
    "load_migrations",
    "tables",
    "table_columns",
    "rls_events",
    "policy_names",
    "validate_schema",
    "CheckResult",
]