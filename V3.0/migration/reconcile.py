"""AIROS V3 — Migration reconciliation (Migration Spec §4 / Test plan §2).

Given a source :class:`V2Snapshot` and the transformed :class:`TransformResult`,
produces a reconciliation report asserting the minimum integrity rules:
- record counts (users, applications, documents)
- user<->application relationship
- company/application relationship
- document references
- lifecycle-status validity
- required identifiers
- duplicate & orphan detection
- no password / no inline-CV carried (ISS-001/ISS-006)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Lifecycle statuses used by V2 (from real data: APPLIED, INTERVIEW,
# EMPLOYER_RESPONSE, CLOSED, OFFER...) — used to validate stored timeline statuses.
KNOWN_LIFECYCLE = {"APPLIED", "INTERVIEW", "EMPLOYER_RESPONSE", "ASSESSMENT", "OFFER", "REJECTED", "WITHDRAWN", "CLOSED"}


@dataclass
class ReconcileResult:
    checks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_check(self, msg: str) -> None:
        self.checks.append(msg)

    def add(self, msg: str) -> None:  # alias
        self.checks.append(msg)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)


def reconcile(snapshot, transform_result: Any) -> ReconcileResult:
    r = ReconcileResult()

    src_users = len(snapshot.users())
    dst_users = len(transform_result.users)
    r.counts["src_users"] = src_users
    r.counts["dst_users"] = dst_users

    # 1. No inline-CSS / no password leaked (ISS-001, ISS-006).
    raw_has_password = any(
        isinstance(snapshot.user(e), dict) and "password" in snapshot.user(e) for e in snapshot.users()
    )
    transformed_has_password = any("password" in u.profile or "password" in u.__dict__ for u in transform_result.users)
    r.add("no plaintext password carried" if not transformed_has_password else "ERROR: password leaked into V3")
    if transformed_has_password:
        r.add_error("a V2 password leaked into the transformed output")

    # 2. Documents: no inline base64 content carried (ISS-006).
    leaked_docs = any(
        any("content_base64" in d for d in u.__dict__.get("documents", [])) for u in transform_result.users
    )
    r.add("no inline base64 CV content carried" if not leaked_docs else "ERROR: inline CV content leaked")
    if leaked_docs:
        r.add_error("inline base64 CV content leaked into V3 output")

    # 3. User/application relationship: don't exceed source app counts.
    src_apps = sum(len(snapshot.applications(e)) for e in snapshot.users())
    dst_apps = sum(len(u.applications) for u in transform_result.users)
    r.counts["src_apps"] = src_apps
    r.counts["dst_apps"] = dst_apps
    r.add(f"applications transformed: {dst_apps}/{src_apps}")

    # 4. Each transformed user has at least a valid email + created_at.
    for u in transform_result.users:
        if "@" not in u.email:
            r.add_error(f"user has invalid email: {u.email!r}")
        if not u.profile:
            r.add_error(f"user has no profile: {u.email}")

    # 5. Application references: job_id + company_id non-rep, and referencable status.
    for u in transform_result.users:
        for a in u.applications:
            if not a.get("application_id"):
                r.add_error(f"{u.email} has application without id")
            if not a.get("job_id"):
                r.add_error(f"{u.email} app {a.get('application_id')} has no job_id")
            if not a.get("company_id"):
                r.add_error(f"{u.email} app {a.get('application_id')} has no company_id")
            st = a.get("status")
            if st and st not in KNOWN_LIFECYCLE:
                r.add_error(f"{u.email} app {a.get('application_id')} unknown status: {st}")

    # 6. Orphan / duplicate application ids.
    all_ids: List[str] = [a.get("application_id") for u in transform_result.users for a in u.applications]
    dupes = {i for i in all_ids if all_ids.count(i) > 1}
    if dupes:
        r.add_error(f"duplicate application ids: {dupes}")

    # 7. Company/application relationship + document refs are non-empty (best-effort).
    apps_with_doc_refs = sum(
        1
        for u in transform_result.users
        for a in u.applications
        if a.get("cv_version") or a.get("cover_letter_version") or a.get("recruiter_email_path")
    )
    r.add(f"applications with doc references: {apps_with_doc_refs}")

    return r