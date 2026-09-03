"""AIROS V3 — Migration package.

Implements the Migration Specification pipeline (Extract -> Validate src ->
Transform -> Load staging -> Validate staging -> Load V3 -> Reconcile) against
the frozen V2 snapshot, applying the register's business-safe migration rules.

Modules:
- snapshot.py   : load the frozen ``data/users_db.json`` snapshot
- transform.py  : Preserve/Transform/Recalculate/Discard rules -> V3 shape
- reconcile.py  : data-integrity checks (Migration Spec §4)
- runner.py     : end-to-end pipeline + reconciliation report
"""

from migration.snapshot import V2Snapshot, load_snapshot, locate_snapshot, SnapshotNotFoundError
from migration.transform import TransformResult, V3User, transform_users, transform_profile
from migration.reconcile import ReconcileResult, reconcile
from migration.runner import run_migration

__all__ = [
    "V2Snapshot",
    "load_snapshot",
    "locate_snapshot",
    "SnapshotNotFoundError",
    "TransformResult",
    "V3User",
    "transform_users",
    "transform_profile",
    "ReconcileResult",
    "reconcile",
    "run_migration",
]