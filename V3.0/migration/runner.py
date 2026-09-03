"""AIROS V3 — Migration runner / pipeline driver.

Ties together the Migration Spec §3 flow:

    V2 snapshot -> Extract -> Validate source -> Transform -> Load staging
                  -> Validate staging -> Load V3 -> Reconcile counts + rels

Deliberately writes nothing to persistent storage: it emits a JSON *report* to
an output path (or ``None`` for stdout). Loading into the live V3 database is a
separate, gated step executed only after the Go/No-Go gate passes (CHG-005).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from migration.snapshot import load_snapshot, V2Snapshot
from migration.transform import transform_users, TransformResult
from migration.reconcile import reconcile, ReconcileResult


@dataclass
class MigrationReport:
    """Full, reproducible result of one migration run (repeatable - Spec §6)."""
    source_path: str
    counts: Dict[str, int]
    checks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    users: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "ok": self.ok,
            "counts": self.counts,
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "users": self.users,
            "documents": self.documents,
        }


def _profile_public(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Strip anything sensitive before including in the report (belt + braces)."""
    return {
        k: (v if k != "identity" else {ik: iv for ik, iv in v.items() if ik != "email"})
        for k, v in profile.items()
    }


def run_migration(snapshot_path: Optional[str] = None) -> MigrationReport:
    """Execute the migration pipeline and return a full report."""
    snapshot: V2Snapshot = load_snapshot(snapshot_path)

    # Transform (side-effect free).
    t_result: TransformResult = transform_users(snapshot, discard_test_user=True)

    # Validate staging.
    rec: ReconcileResult = reconcile(snapshot, t_result)

    # Serialize a public (non-PII-sensitive) report for the audit trail.
    report = MigrationReport(
        source_path=str(snapshot.path),
        counts=rec.counts,
        checks=rec.checks,
        errors=rec.errors,
        warnings=list(t_result.warnings),
        users=[
            {
                "email": u.email,
                "verified": u.verified,
                "created_at": u.created_at,
                "profile": _profile_public(u.profile),
                "applications": u.applications,
            }
            for u in t_result.users
        ],
        documents=list(t_result.documents),
    )
    return report


def save_report(report: MigrationReport, out: Path) -> None:
    """Write the report to JSON (used by tests / CI)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:  # CLI entrypoint for a manual dry-run.
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="AIROS V3 migration dry-run")
    parser.add_argument("--snapshot", default=None, help="Path to V2 users_db.json")
    parser.add_argument("--out", default=None, help="Optional JSON report output path")
    args = parser.parse_args()

    report = run_migration(args.snapshot)
    if report.ok:
        print("OK - migration reconcile passed")
    else:
        for e in report.errors:
            print(f"  ERROR: {e}")
    for w in report.warnings:
        print(f"  WARN : {w}")
    for c in report.checks:
        print(f"  check: {c}")
    print("counts:", report.counts)

    if args.out:
        save_report(report, Path(args.out))
        print(f"report written -> {args.out}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())