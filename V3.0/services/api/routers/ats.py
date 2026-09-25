"""AIROS V3 - ATS Job Analyzer router (DEC-006 increment).

`POST /api/ats/analyze` - pasted Job Description -> ONE Gemini call (job
parse through the AI gateway) -> deterministic V2 ATS engine -> blocked by
the ATS threshold + hard-bottleneck gating.

Security posture (same as the profile router, DEC-013/DEC-014):
- the caller's OWN profile is read via PostgREST **with the caller's token**
  (RLS-scoped, no service_role key);
- the Gemini key is read from the server env only (ISS-004);
- the engine is fully deterministic (R06: scores are derived, not sourced).

Returns the full V2-shaped result plus a ``verdict`` used by the UI to gate
the "move to another JD" (NO) vs "post-ATS assessment process" (YES) flow:
  verdict.band in {"hard_reject", "soft_reject", "blockers"} -> NO
  verdict.band in {"manual", "proceed"}                       -> YES (manual needs approval)
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai.ats import calculate_ats_gap
from ai.gateway import GatewayError
from services.api.auth import bearer_token, current_claims
from services.api.config import get_settings

router = APIRouter(prefix="/api/ats")


class AnalyzeRequest(BaseModel):
    job_text: str
    force_refresh: bool = False


def _gemini_key() -> str:
    """Server-side Gemini key (ISS-004: only the gateway layer sees it)."""
    return os.getenv("GEMINI_API_KEY", "")


def _fetch_own_profile(token: str) -> dict:
    """Read the caller's OWN profiles row via PostgREST with their token (RLS)."""
    settings = get_settings()
    try:
        resp = httpx.get(
            f"{settings.supabase_url}/rest/v1/profiles",
            params={"select": "*", "limit": "1"},
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if isinstance(rows, list) and rows:
                return rows[0]
    except Exception:
        pass
    return {}


@router.post("/analyze")
def analyze_job(
    req: AnalyzeRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    if not req.job_text or not req.job_text.strip():
        raise HTTPException(status_code=422, detail="job_text is required")

    profile = _fetch_own_profile(token)
    if not profile:
        raise HTTPException(
            status_code=409,
            detail="No profile found. Build your profile first (Road A or Road B).",
        )

    api_key = _gemini_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY missing on the server.")

    try:
        return calculate_ats_gap(
            profile,
            req.job_text,
            api_key,
            force_refresh=req.force_refresh,
        )
    except GatewayError as exc:
        # V2: clean deterministic failure -> user can retry; never a silent swap.
        raise HTTPException(status_code=502, detail=str(exc)) from exc