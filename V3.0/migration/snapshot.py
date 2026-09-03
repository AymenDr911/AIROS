"""AIROS V3 — Migration source snapshot loader.

Reads the frozen V2 runtime snapshot (``data/users_db.json``) and exposes it as
typed, defensively-parsed structures. The real V2 file lives OUTSIDE source
control (gitignored: ``data/users_db.json``), so this loader treats it as a
read-only recovery/reference baseline (Architecture Baseline §4).

Per register ISS-001/002/006, no password, demo/test record, or inline base64
document content ever leaves this snapshot; they are handled in `transform.py`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class SnapshotNotFoundError(FileNotFoundError):
    """Raised when the V2 snapshot file cannot be located."""


@dataclass
class V2Snapshot:
    """Loaded V2 user database with per-user accessors."""
    raw: Dict[str, Any]
    path: Path

    def users(self) -> List[str]:
        return sorted(self.raw.keys())

    def user(self, email: str) -> Dict[str, Any]:
        """Return a user record or empty dict (defensive)."""
        record = self.raw.get(email)
        return record if isinstance(record, dict) else {}

    def profile(self, email: str) -> Dict[str, Any]:
        p = self.user(email).get("profile")
        return p if isinstance(p, dict) else {}

    def applications(self, email: str) -> List[Dict[str, Any]]:
        apps = self.user(email).get("applications")
        if isinstance(apps, dict):
            return list(apps.values())
        if isinstance(apps, list):
            return apps
        return []


def locate_snapshot(explicit: Optional[str] = None) -> Path:
    """Resolve the V2 snapshot path.

    Order:
      1. explicit argument (path string)
      2. env ``AIROS_V2_SNAPSHOT``
      3. default sibling of this V3 package: repo_root/V2.0/data/users_db.json
    """
    for c in (explicit, os.getenv("AIROS_V2_SNAPSHOT")):
        if c and Path(c).is_file():
            return Path(c)

    here = Path(__file__).resolve()
    v3_root = here.parents[1]          # .../AIROS/V3.0
    repo_root = v3_root.parent         # .../AIROS
    default = repo_root / "V2.0" / "data" / "users_db.json"
    if default.is_file():
        return default

    raise SnapshotNotFoundError(
        f"V2 snapshot not found; tried explicit/env and {default}. "
        "Set AIROS_V2_SNAPSHOT to the users_db.json path."
    )


def load_snapshot(explicit: Optional[str] = None) -> V2Snapshot:
    """Load and parse the V2 snapshot JSON into a :class:`V2Snapshot`."""
    p = locate_snapshot(explicit)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"V2 snapshot is not valid JSON: {p}") from exc
    if not isinstance(raw, dict):
        raise ValueError("V2 snapshot root must be an object keyed by email.")
    return V2Snapshot(raw=raw, path=p)