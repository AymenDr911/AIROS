"""Profile creation flow (Slice 6, CHG-014) - exact V2 parity endpoints.

Road A (manual) and Road B (AI-powered CV extraction), ported from V2
``app/onboarding/cv_choice.py`` + ``services/cv_extractor.py``:

- ``POST /api/profile/extract-cv``: upload 1+ PDF/DOCX -> text extraction
  (V2 order: PyMuPDF -> pypdf; python-docx for DOCX) -> Gemini extraction
  through the AI gateway (DEC-005) -> original files saved to the local
  protected uploads dir (V2 ``data/uploads`` behavior; ISS-006: metadata
  only in the DB) -> returns the rich prefill data + CV stub metadata.
- ``PUT /api/profile``: receives the V2-shaped profile payload, runs the
  EXACT ``migration.transform.transform_profile`` (same reclassify/evidence
  rules as the migration), and upserts the caller's own ``profiles`` row via
  PostgREST WITH THE CALLER'S TOKEN (RLS enforced, DEC-013/DEC-014).

The Gemini key is read from the server-side env only (ISS-004) - never in
the web frontend.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ai.gateway import GatewayError, extract_rich_profile_from_text
from migration.transform import has_strength_evidence, transform_profile
from services.api.auth import bearer_token, current_claims
from services.api.config import get_settings
from services.api.cv_text import CvTextError, extract_text_from_multiple

router = APIRouter(prefix="/api/profile")

ALLOWED_CV_EXTENSIONS = (".pdf", ".docx")
MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB per file (sane guard; V2 had none)

# V2 onboarding career stages (career_stage.py), verbatim
CAREER_STAGES = [
    "Student / Recent Graduate",
    "Looking for Internship",
    "Entry-Level Professional (0–2 years)",
    "Experienced Professional (3–8 years)",
    "Senior Expert / Manager (8+ years)",
    "Freelancer / Consultant",
    "Entrepreneur / Business Owner",
    "Career Transition / Changing Path",
]


def _gemini_key() -> str:
    """Server-side Gemini key (ISS-004: only the gateway layer sees it)."""
    return os.getenv("GEMINI_API_KEY", "")


def _uploads_root() -> Path:
    """Local protected uploads dir (V2 parity). DEC-012 will swap the store."""
    return Path("data") / "uploads"


def _save_original_cvs(files: list[tuple[str, bytes]], owner_sub: str) -> list[dict]:
    """V2 ``_save_original_cvs``: persist originals on disk, return metadata.

    V3 change: the folder is keyed by the account's Auth0 subject (opaque id)
    instead of the raw email - no personal data in paths (GDPR/R03).
    """
    safe_dir = "".join(ch if ch.isalnum() or ch in "|-" else "_" for ch in owner_sub)
    upload_dir = _uploads_root() / safe_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for idx, (original_name, data) in enumerate(files, start=1):
        ext = Path(original_name).suffix.lower() or ".pdf"
        filename = f"original_cv_{idx}{ext}"
        filepath = upload_dir / filename
        filepath.write_bytes(data)

        saved_files.append({
            "original_name": original_name,
            "saved_as": filename,
            "path": str(filepath),           # dev-local store (DEC-012 swap later)
            "storage_ref": f"local://{filepath.as_posix()}",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "size_kb": round(len(data) / 1024, 1),
        })

    return saved_files


def _account_id(token: str) -> str:
    """Resolve the caller's own accounts.id via PostgREST (RLS-scoped)."""
    import httpx

    settings = get_settings()
    resp = httpx.get(
        f"{settings.supabase_url}/rest/v1/accounts",
        params={"select": "id", "limit": 1},
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=15.0,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"upstream PostgREST error: HTTP {resp.status_code}")
    rows = resp.json()
    if not rows:
        raise HTTPException(status_code=409, detail="account not provisioned yet; sign in again to sync it")
    return rows[0]["id"]


@router.post("/extract-cv")
async def extract_cv(
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
    files: list[UploadFile] = File(...),
) -> dict:
    """Road B - V2 ``extract_rich_profile`` flow, exactly.

    Returns {rich_data, saved_files, strong_evidence} for form prefill.
    """
    if not files:
        raise HTTPException(status_code=400, detail="no CV file uploaded")

    # Read + validate (V2 accepted pdf/docx only)
    pairs: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or ""
        if not name.lower().endswith(ALLOWED_CV_EXTENSIONS):
            raise HTTPException(status_code=400, detail=f"unsupported file type: {name} (PDF or DOCX only)")
        data = await f.read()
        if len(data) > MAX_CV_BYTES:
            raise HTTPException(status_code=413, detail=f"file too large: {name} (max 10 MB)")
        pairs.append((name, data))

    # 1. Text extraction (V2 order)
    try:
        raw_text = extract_text_from_multiple(pairs)
    except CvTextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 2. Gemini extraction through the gateway (V2 prompt/behavior)
    try:
        rich_data = extract_rich_profile_from_text(raw_text, _gemini_key())
    except GatewayError as exc:
        # V2: "Extraction failed. Please try again or use Manual Mode."
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not rich_data:
        raise HTTPException(status_code=502, detail="Extraction failed. Please try again or use Manual Mode.")

    # 3. Persist originals (V2 behavior; metadata-only in DB, ISS-006)
    saved_files = _save_original_cvs(pairs, str(claims["sub"]))

    # 4. Strong evidence with the SAME rule as the migration
    strong_evidence = has_strength_evidence(rich_data.get("professional_experience"))

    return {
        "rich_data": rich_data,
        "saved_files": saved_files,
        "strong_evidence": strong_evidence,
        "career_stage_suggestion": rich_data.get("career_stage_suggestion", ""),
    }


@router.put("")
def save_profile(
    payload: dict,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    """Persist the profile built by Road A or Road B.

    The payload keeps the V2 shapes (personal_identity, skills
    {technical, methodologies, tools, core}, ...); the EXACT migration
    ``transform_profile`` converts them to the V3 row, so onboarding data and
    migrated data are indistinguishable downstream.
    """
    import httpx

    settings = get_settings()
    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    # V2-shaped profile object (same keys the V2 session carried)
    v2_profile = {
        "career_stage": str(payload.get("career_stage", "") or ""),
        "personal_identity": payload.get("personal_identity") or {},
        "education": payload.get("education") or [],
        "experience": payload.get("experience") or [],
        "skills": payload.get("skills") or {},
        "languages": payload.get("languages") or [],
        "certifications": payload.get("certifications") or [],
        "profile_method": str(payload.get("profile_method", "") or ""),
        "onboarding_completed": bool(payload.get("onboarding_completed", False)),
        "original_cv_files": payload.get("saved_files") or [],
    }

    if v2_profile["career_stage"] and v2_profile["career_stage"] not in CAREER_STAGES:
        raise HTTPException(status_code=422, detail="unknown career stage")

    if not isinstance(v2_profile["personal_identity"], dict) or not v2_profile["personal_identity"]:
        raise HTTPException(status_code=422, detail="personal_identity is required")

    # EXACT migration transform (skills reclassify, evidence rule, identity map)
    v3_profile = transform_profile(v2_profile)

    account_id = _account_id(token)
    row = {"account_id": account_id, **v3_profile}

    # Upsert the caller's own profiles row (RLS: account_id must be theirs)
    resp = httpx.post(
        f"{settings.supabase_url}/rest/v1/profiles",
        params={"on_conflict": "account_id"},
        headers=headers,
        json=row,
        timeout=20.0,
    )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"profile upsert failed: HTTP {resp.status_code}: {resp.text[:300]}",
        )

    saved = resp.json()
    return {"profile": saved[0] if isinstance(saved, list) and saved else saved}


