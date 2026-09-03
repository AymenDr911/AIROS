"""AIROS V3 — Migration transform rules.

Implements the Migration Specification §2 rules as pure functions, applied to a
:class:`~migration.snapshot.V2Snapshot`. Each rule is auditable and unit-tested.

Business-safe rules enforced (per register ISS-001/002/006 + DEC-004/DEC-007):
- Discard demo/test users (ISS-002) and never carry a V2 password (ISS-001).
- Discard inline base64 CV content (ISS-006) -> emit a document stub to be
  materialized into the protected document store later.
- Transform (preserve) profile structure.
- Reclassify V2 ``skills`` into the V3 taxonomy: technical/core/management/soft/other.
- Transform applications, preserving lifecycle history + time-consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Uppercase, unambiguous V3 skill categories.
categories = ("TECHNICAL", "CORE", "MANAGEMENT", "SOFT", "OTHER")

# V2 source-category -> V3 category mapping.
_V2_CATEGORY_MAP = {
    "technical": "TECHNICAL",
    "tools": "TECHNICAL",
    "methodologies": "MANAGEMENT",
    "core": "CORE",
    "soft": "SOFT",
}

# Keywords to disambiguate management vs soft skills when source category is generic.
_MANAGEMENT_KEYWORDS = ("lead", "manag", "coordinat", "direct", "govern", "stakeholder", "planning")
_SOFT_KEYWORDS = ("communicat", "collaborat", "team", "negotiat", "influenc", "present")


@dataclass
class TransformResult:
    """Flattened output of a single migration run (pre-loading)."""
    users: List[Any] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def user_map(self) -> Dict[str, Any]:
        return {u.email: u for u in self.users}


@dataclass
class V3User:
    email: str
    verified: bool
    created_at: str
    profile: Dict[str, Any]
    applications: List[Dict[str, Any]]
    documents: List[Dict[str, Any]]
    source_key: str


def _classify_skill(name: str, source_cat: str) -> str:
    """Map a single V2 skill into the V3 taxonomy using source category, then keywords."""
    mapped = _V2_CATEGORY_MAP.get(str(source_cat).lower())
    if mapped:
        return mapped
    low = name.lower()
    if any(k in low for k in _MANAGEMENT_KEYWORDS):
        return "MANAGEMENT"
    if any(k in low for k in _SOFT_KEYWORDS):
        return "SOFT"
    return "TECHNICAL"


def reclassify_skills(v2_skills: Any) -> Dict[str, List[str]]:
    """Return {CATEGORY: [skill, ...]} from a V2 ``skills`` blob."""
    by_cat: Dict[str, List[str]] = {c: [] for c in categories}
    if not isinstance(v2_skills, dict):
        return by_cat
    for src_cat, items in v2_skills.items():
        if not isinstance(items, list):
            continue
        for item in items:
            name = item if isinstance(item, str) else (item.get("name") if isinstance(item, dict) else None)
            if not name:
                continue
            by_cat[_classify_skill(name, src_cat)].append(name)
    return by_cat


def has_strength_evidence(experience: Any) -> bool:
    """Detect strong evidence: any role with >= 3 total years (incl. active).

    V2 dates use ``MM.YYYY`` (e.g. ``01.2016`` = Jan 2016), so the year is the
    last numeric token; ``Present``/open-ended is handled by spelling checks.
    """

    def _year(s: str):
        s = s.strip()
        if not s:
            return None
        low = s.lower()
        if low in ("present", "now", "current", "today", "ongoing"):
            return None
        # Last whitespace/dot/slash/hyphen-separated token that is 4 digits -> year.
        import re
        m = re.findall(r"\b(1\d{3}|20\d{2})\b", s)
        return int(m[-1]) if m else None

    def _years(start: str, end: str) -> Optional[float]:
        try:
            sy, ey = _year(str(start or "")), _year(str(end or ""))
        except (ValueError, TypeError):
            return None
        if sy is None or ey is None:
            return None
        return float(ey - sy)

    if isinstance(experience, list):
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            if exp.get("currently_working") and str(exp.get("start_date", "")).strip():
                return True  # open-ended active role counts as strong evidence
            ny = _years(exp.get("start_date"), exp.get("end_date"))
            if ny is not None and ny >= 3:
                return True
    return False


def transform_users(snapshot, discard_test_user: bool = True) -> TransformResult:
    """Run the transform over all users in a snapshot (pure, side-effect free).

    ``discard_test_user`` controls the demo/test-record rule (CHG-002); it is
    True by default so production runs never carry demo/test accounts.
    """
    result = TransformResult()
    for email in snapshot.users():
        rec = snapshot.user(email)
        if discard_test_user and (
            "@airos.demo" in email.lower()
            or email.lower().startswith("test@")
            or str(rec.get("verification_token", "")).upper() == "AIROS-TEST"
        ):
            result.warnings.append(f"discarded demo/test account: {email}")
            continue

        profile = transform_profile(snapshot.profile(email))
        apps = [transform_application(a) for a in snapshot.applications(email) if isinstance(a, dict)]
        documents = extract_document_stubs(snapshot.profile(email))
        result.users.append(
            V3User(
                email=email,
                verified=str(rec.get("status", "")).upper() == "ACTIVE",
                created_at=str(rec.get("created_at", "")),
                profile=profile,
                applications=apps,
                documents=documents,
                source_key=email,
            )
        )
        # Collect stubs for the consolidated document list.
        for d in documents:
            d = dict(d)
            d["owner_email"] = email
            result.documents.append(d)
    return result


def transform_profile(v2_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a V2 profile object into the V3 shape (no passwords, no inline CV)."""
    identity = v2_profile.get("personal_identity")
    if not isinstance(identity, dict):
        identity = {}
    return {
        "career_stage": v2_profile.get("career_stage", ""),
        "identity": {
            k: identity.get(k, "")
            for k in ("full_name", "email", "phone", "location", "linkedin", "github", "portfolio", "summary")
        },
        "education": v2_profile.get("education", []) if isinstance(v2_profile.get("education"), list) else [],
        "experience": v2_profile.get("experience", []) if isinstance(v2_profile.get("experience"), list) else [],
        "skills": reclassify_skills(v2_profile.get("skills")),
        "languages": v2_profile.get("languages", []) if isinstance(v2_profile.get("languages"), list) else [],
        "certifications": v2_profile.get("certifications", [])
        if isinstance(v2_profile.get("certifications"), list)
        else [],
        "strong_evidence": has_strength_evidence(v2_profile.get("experience")),
        "original_cv_count": len(v2_profile.get("original_cv_files", []))
        if isinstance(v2_profile.get("original_cv_files"), list)
        else 0,
    }


def transform_application(v2_app: Dict[str, Any]) -> Dict[str, Any]:
    """Transform an application record, preserving lifecycle/history + time-consumed."""
    return {
        "application_id": v2_app.get("application_id", ""),
        "job_id": v2_app.get("job_id", ""),
        "company_id": v2_app.get("company_id", ""),
        "title": v2_app.get("title", ""),
        "status": v2_app.get("status", ""),
        "application_date": v2_app.get("application_date", ""),
        "created_at": v2_app.get("created_at", ""),
        "updated_at": v2_app.get("updated_at", ""),
        "ats_score": v2_app.get("ats_score"),  # historical only; recalculated in V3
        "time_consumed_min": v2_app.get("time_consumed_min"),
        "recruiter_name": v2_app.get("recruiter_name", ""),
        "recruiter_email": v2_app.get("recruiter_email", ""),
        "outcome": v2_app.get("outcome"),
        "timeline": v2_app.get("timeline", []) if isinstance(v2_app.get("timeline"), list) else [],
        "interviews": v2_app.get("interviews", []) if isinstance(v2_app.get("interviews"), list) else [],
        "cv_version": v2_app.get("cv_version", ""),
        "cover_letter_version": v2_app.get("cover_letter_version", ""),
        "recruiter_email_path": v2_app.get("recruiter_email_path", ""),
    }


def extract_document_stubs(v2_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return lightweight document metadata; content itself is NOT migrated
    (ISS-006). The actual bytes go to a protected document store later."""
    files = v2_profile.get("original_cv_files", [])
    out: List[Dict[str, Any]] = []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict):
                continue
            out.append(
                {
                    "original_name": f.get("original_name", ""),
                    "saved_as": f.get("saved_as", ""),
                    "uploaded_at": f.get("uploaded_at", ""),
                    "size_kb": f.get("size_kb", 0),
                    "mime": f.get("mime", ""),
                    # NOTE: content_base64 intentionally omitted (ISS-006).
                }
            )
    return out