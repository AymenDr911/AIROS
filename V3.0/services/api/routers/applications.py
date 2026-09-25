"""AIROS V3 - Application workspace router (CHG-018).

Full V2 post-ATS workflow parity (Job Application + Job Tracking), with the
established V3 security posture (same as the profile router, DEC-013/DEC-014):

- every read/write goes to Supabase PostgREST WITH THE CALLER'S TOKEN, so
  per-account RLS stays the isolation boundary (ISS-003);
- identity is never taken from client fields - only the verified Auth0 sub;
- the Gemini key is read from the server env only (ISS-004);
- all lifecycle logic is the deterministic port in ``ai/lifecycle.py``
  (manual-only transitions; the system never auto-advances an application).

Endpoints (all under /api/applications):
    POST /jobs                      save analyzed JD (+company, +contact) - V2 save_job
    POST /jobs/{job_id}/contacts    link another recruiter contact - V2 add_contact_to_job
    POST /jobs/{job_id}/documents   document engine (ONE Gemini call) + validation
    POST                            confirm application (sent -> APPLIED record)
    GET  /{application_id}          detail + allowed transitions + next action
    POST /{application_id}/status | /response | /interview | /followup
        | /remind-later | /response-date | /closing-date | /close
    GET  /documents/{document_id}/content   auth-gated generated-document download
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from ai import lifecycle as lc
from ai.ats import build_candidate_json
from ai.document_validation import validate_generated_documents
from ai.documents import find_reliable_contact, generate_application_documents
from ai.gateway import GatewayError
from documents.builders import build_cover_letter_document, build_cv_document
from documents.docx_renderer import render_document
from documents.pdf_renderer import PdfConversionError, convert_docx_to_pdf, libreoffice_available
from documents.validation import validate_document_model, validate_rendered_document
from services.api.auth import bearer_token, current_claims
from services.api.config import get_settings

router = APIRouter(prefix="/api/applications")


# =============================================================================
# Request models
# =============================================================================
class ContactIn(BaseModel):
    name: str = ""
    position: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    contact_type: str = "HR Recruiter"
    source: str = "Manual"
    confidence: str = "Medium"


class SaveJobRequest(BaseModel):
    analysis: Dict[str, Any]                    # the CHG-017 calculate_ats_gap result
    original_jd: str
    job_title: str = ""
    company_name: str = ""
    location: str = ""
    country: str = ""
    job_url: str = ""
    source: str = "Manual paste"
    department: str = ""
    contact: Optional[ContactIn] = None


class DocumentsRequest(BaseModel):
    generate_cv: bool = True
    generate_cover_letter: bool = True
    generate_recruiter_email: bool = True


class ConfirmApplicationRequest(BaseModel):
    job_id: str
    decision: str                                # "sent" | "cancelled"
    channel: str = ""
    application_date: str = ""
    notes: str = ""


class StatusRequest(BaseModel):
    new_status: str
    note: str = ""


class ResponseRequest(BaseModel):
    response_type: str                           # REFUSED | INTERVIEW_REQUEST | ADDITIONAL_INFO_REQUEST
    channel: str = "Email"
    responded_on: str = ""
    note: str = ""


class InterviewRequest(BaseModel):
    round_no: int
    scheduled_at: str
    mode: str = "Online (video call)"
    notes: str = ""


class FollowUpRequest(BaseModel):
    contacted_at: str = ""
    channel: str = "Email"
    note: str = ""


class RemindLaterRequest(BaseModel):
    days: int = lc.FOLLOW_UP_INTERVAL_DAYS


class DateRequest(BaseModel):
    date: str


class CloseRequest(BaseModel):
    note: str = ""


# =============================================================================
# PostgREST helpers (caller's token forwarded - RLS is the boundary)
# =============================================================================
def _gemini_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def _pgr_headers(token: str) -> Dict[str, str]:
    settings = get_settings()
    return {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _pgr_get(token: str, table: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    """GET rows via PostgREST with the caller's token; 502 on upstream error."""
    settings = get_settings()
    resp = httpx.get(
        f"{settings.supabase_url}/rest/v1/{table}",
        params=params,
        headers=_pgr_headers(token),
        timeout=15.0,
    )
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict) and data.get("code") == "PGRST205":
        # PostgREST schema cache: the table is unknown to the API, which for
        # the workspace tables means migration 0006 was never applied (or the
        # API was not reloaded after applying it). Surface an actionable 409,
        # not a cryptic 502/404 chain.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workspace tables are missing on the database "
                f"(PostgREST has no '{table}'). Apply "
                f"database/migrations/0006_application_workspace.sql and "
                f"0007_rls_extension.sql in the Supabase SQL Editor, then reload "
                f"the PostgREST schema cache (or wait ~1 min) and retry."
            ),
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"upstream PostgREST error on {table}: HTTP {resp.status_code}",
        )
    return data if isinstance(data, list) else []


def _pgrst204_missing_column(resp_text: str) -> str:
    """The unknown column named by PostgREST error PGRST204, if any.

    PGRST204 = "Could not find the 'phone' column of 'contacts' in the schema
    cache" - raised when a row carries a column that migration 0008 has not
    created on the live database yet (user-reported failure on the
    Save Job + Company + Recruiter step).
    """
    m = re.search(r"Could not find the '([A-Za-z_][A-Za-z0-9_]*)' column", resp_text or "")
    return m.group(1) if m else ""


_MISSING_COLUMN_ADVICE = (
    "Apply database/migrations/0008_workspace_approval.sql in the Supabase SQL "
    "Editor (it adds contacts.phone and the jobs/applications timestamp columns), "
    "then retry."
)


def _note_column_dropped(table: str, column: str, warnings: Optional[List[str]]) -> None:
    """Report a dropped column to the caller (never silently lost)."""
    msg = (
        f"Database column '{table}.{column}' is missing (migration 0008 not applied) "
        f"- that value was NOT saved. {_MISSING_COLUMN_ADVICE}"
    )
    if warnings is None:
        logging.getLogger("uvicorn.error").warning(msg)
    else:
        warnings.append(msg)


def _pgr_insert(
    token: str, table: str, row: Dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    headers = _pgr_headers(token)
    headers["Prefer"] = "return=representation"

    def _post(payload: Dict[str, Any]):
        return httpx.post(
            f"{settings.supabase_url}/rest/v1/{table}",
            params={},
            headers=headers,
            json=payload,
            timeout=20.0,
        )

    resp = _post(row)
    if resp.status_code in (404,) or "PGRST205" in (resp.text or ""):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workspace tables are missing on the database "
                f"(PostgREST has no '{table}'). Apply "
                f"database/migrations/0006_application_workspace.sql and "
                f"0007_rls_extension.sql in the Supabase SQL Editor, then reload "
                f"the PostgREST schema cache (or wait ~1 min) and retry."
            ),
        )
    # PGRST204 resilience (CHG-024): when the row carries a column that migration
    # 0008 has not applied to the live DB yet, retry ONCE without it so saving
    # company + RH data never hard-fails. The dropped value is reported (warning
    # list or server log) - never silently lost.
    missing = _pgrst204_missing_column(resp.text)
    if resp.status_code not in (200, 201) and missing and missing in row:
        _note_column_dropped(table, missing, warnings)
        resp = _post({k: v for k, v in row.items() if k != missing})
    elif resp.status_code not in (200, 201) and missing:
        _note_column_dropped(table, missing, None)
    if resp.status_code not in (200, 201):
        detail = f"{table} insert failed: HTTP {resp.status_code}: {resp.text[:300]}"
        if missing:
            detail += f" - {_MISSING_COLUMN_ADVICE}"
        raise HTTPException(
            status_code=502,
            detail=detail,
        )
    saved = resp.json()
    return saved[0] if isinstance(saved, list) and saved else saved


def _pgr_update(
    token: str,
    table: str,
    filters: Dict[str, str],
    patch: Dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    headers = _pgr_headers(token)
    headers["Prefer"] = "return=representation"

    def _patch(payload: Dict[str, Any]):
        return httpx.patch(
            f"{settings.supabase_url}/rest/v1/{table}",
            params=filters,
            headers=headers,
            json=payload,
            timeout=20.0,
        )

    resp = _patch(patch)
    # PGRST204 resilience (CHG-024): same retry-without-unknown-column rule as
    # the insert path (e.g. jobs.docs_generated_at before migration 0008).
    missing = _pgrst204_missing_column(resp.text)
    if resp.status_code not in (200, 204) and missing and missing in patch:
        _note_column_dropped(table, missing, warnings)
        resp = _patch({k: v for k, v in patch.items() if k != missing})
    elif resp.status_code not in (200, 204) and missing:
        _note_column_dropped(table, missing, None)
    if resp.status_code not in (200, 204):
        detail = f"{table} update failed: HTTP {resp.status_code}: {resp.text[:300]}"
        if missing:
            detail += f" - {_MISSING_COLUMN_ADVICE}"
        raise HTTPException(
            status_code=502,
            detail=detail,
        )
    rows = resp.json() if resp.text else []
    return rows[0] if isinstance(rows, list) and rows else None


def _account_id(token: str) -> str:
    rows = _pgr_get(token, "accounts", {"select": "id", "limit": "1"})
    if not rows:
        raise HTTPException(
            status_code=409, detail="account not provisioned yet; sign in again to sync it"
        )
    return rows[0]["id"]


def _uploads_root() -> Path:
    """Local protected document store (CHG-014 precedent). DEC-012 will swap."""
    return Path("data") / "uploads"


def _account_dir(owner_sub: str) -> Path:
    safe_dir = "".join(ch if ch.isalnum() or ch in "|-" else "_" for ch in owner_sub)
    return _uploads_root() / safe_dir


def _fetch_own_profile(token: str) -> Dict[str, Any]:
    """Caller's OWN profiles row via PostgREST with their token (RLS)."""
    rows = _pgr_get(token, "profiles", {"select": "*", "limit": "1"})
    return rows[0] if rows else {}


def _get_job(token: str, account_id: str, job_id: str) -> Dict[str, Any]:
    rows = _pgr_get(token, "jobs", {
        "select": "*", "account_id": f"eq.{account_id}", "job_id": f"eq.{job_id}", "limit": "1"
    })
    if not rows:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return rows[0]


def _get_application(token: str, account_id: str, application_id: str) -> Dict[str, Any]:
    rows = _pgr_get(token, "applications", {
        "select": "*", "account_id": f"eq.{account_id}",
        "application_id": f"eq.{application_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found.")
    return rows[0]


# =============================================================================
# V2 save_job / contact parity helpers
# =============================================================================
def _find_or_create_company(
    token: str, account_id: str, *, name: str, parsed: Dict[str, Any],
    location: str = "", country: str = "",
) -> Dict[str, Any]:
    """V2 find_or_create_company: reuse by (account, lower(name)); enrich gaps."""
    name = (name or "").strip() or "Unknown Company"
    existing = _pgr_get(token, "companies", {
        "select": "*",
        "account_id": f"eq.{account_id}",
        "name": f"ilike.{name}",
        "limit": "1",
    })
    if existing:
        company = existing[0]
        patch: Dict[str, Any] = {}
        for field, value in (
            ("city", parsed.get("city") or location or parsed.get("location", "")),
            ("country", country or parsed.get("country", "")),
            ("address", parsed.get("address", "")),
            ("website", parsed.get("company_website", "")),
            ("linkedin_url", parsed.get("company_linkedin", "")),
            ("phone", parsed.get("company_phone", "")),
            ("industry", parsed.get("industry", "")),
        ):
            if not company.get(field) and value:
                patch[field] = str(value).strip()
        if patch:
            company = _pgr_update(token, "companies", {
                "account_id": f"eq.{account_id}", "company_id": f"eq.{company['company_id']}"
            }, patch) or company
        return company

    ids = [r["company_id"] for r in _pgr_get(token, "companies", {
        "select": "company_id", "account_id": f"eq.{account_id}"
    })]
    company = {
        "account_id": account_id,
        "company_id": lc.next_sequential_id("COMP", ids),
        "name": name,
        "division": str(parsed.get("division", "") or "").strip(),
        "industry": str(parsed.get("industry", "") or "").strip(),
        "address": str(parsed.get("address", "") or "").strip(),
        "city": str(parsed.get("city") or location or parsed.get("location", "") or "").strip(),
        "country": str(country or parsed.get("country", "") or "").strip(),
        "website": str(parsed.get("company_website", "") or "").strip(),
        "careers_website": "",
        "linkedin_url": str(parsed.get("company_linkedin", "") or "").strip(),
        "phone": str(parsed.get("company_phone", "") or "").strip(),
        "general_emails": [],
        "notes": "",
    }
    return _pgr_insert(token, "companies", company)


def _create_contact(
    token: str, account_id: str, company_id: str, data: ContactIn,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """V2 create_contact parity incl. the generic-email downgrade rule."""
    email = (data.email or "").strip()
    contact_type = data.contact_type or "General"
    confidence = data.confidence or "Medium"
    generic_prefixes = ("info@", "contact@", "careers@", "jobs@", "hr@",
                        "recruitment@", "hello@")
    if email and any(email.lower().startswith(p) for p in generic_prefixes):
        contact_type = "General"
        confidence = "Low"

    ids = [r["contact_id"] for r in _pgr_get(token, "contacts", {
        "select": "contact_id", "account_id": f"eq.{account_id}"
    })]
    contact = {
        "account_id": account_id,
        "contact_id": lc.next_sequential_id("CONT", ids),
        "company_id": company_id,
        "name": (data.name or "").strip(),
        "position": (data.position or "").strip(),
        "email": email,
        "phone": (data.phone or "").strip(),
        "linkedin_url": (data.linkedin_url or "").strip(),
        "contact_type": contact_type,
        "source": data.source or "Manual",
        "confidence": confidence,
        "verified": False,
    }
    return _pgr_insert(token, "contacts", contact, warnings=warnings)


def _contact_filled(data: Any) -> bool:
    """True when the contact carries ANY usable field (partial matches count:
    name-only, phone-only, email-only, LinkedIn-only...). Handles both pydantic
    ContactIn instances and plain dicts."""
    for key in ("name", "position", "email", "phone", "linkedin_url"):
        value = getattr(data, key, "") if not isinstance(data, dict) else data.get(key, "")
        if str(value or "").strip():
            return True
    return False


def _rc_filled(rc: Dict[str, Any]) -> bool:
    """True when a parsed JD recruiter_contact carries any usable field."""
    return any(str(rc.get(k) or "").strip() for k in
               ("name", "position", "email", "phone", "linkedin_url"))


# =============================================================================
# Stage 1 - save the analyzed job (V2 save_job + add_contact_to_job)
# =============================================================================
@router.post("/jobs")
def save_analyzed_job(
    req: SaveJobRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    if not req.original_jd or not req.original_jd.strip():
        raise HTTPException(status_code=422, detail="original_jd is required")
    analysis = req.analysis or {}
    if not analysis.get("parsed_job"):
        raise HTTPException(status_code=422, detail="analysis.parsed_job is missing - analyze the JD first")

    account_id = _account_id(token)
    parsed = analysis.get("parsed_job") or {}

    # PGRST204 resilience (CHG-024): collect human-readable notices when a
    # column of migration 0008 is not applied yet, and surface them to the UI.
    schema_warn: List[str] = []

    company = _find_or_create_company(
        token, account_id,
        name=req.company_name or parsed.get("company_name") or "Unknown Company",
        parsed=parsed,
        location=req.location or parsed.get("location", ""),
        country=req.country or parsed.get("country", ""),
    )

    job_ids = [r["job_id"] for r in _pgr_get(token, "jobs", {
        "select": "job_id", "account_id": f"eq.{account_id}"
    })]
    job = {
        "account_id": account_id,
        "job_id": lc.next_sequential_id("JOB", job_ids),
        "company_id": company["company_id"],
        "title": req.job_title or parsed.get("job_title") or "Untitled Position",
        "department": req.department or parsed.get("department", ""),
        "location": req.location or parsed.get("location", ""),
        "country": req.country or parsed.get("country", ""),
        "job_url": req.job_url or parsed.get("job_url", ""),
        "source": req.source or "Manual",
        "original_jd": req.original_jd,
        "job_json": parsed,
        "publication_date": str(parsed.get("publication_date") or ""),
        "analysis_date": lc.now_iso()[:10],
        "ats_score": analysis.get("ats_score", 0),
        "ats_components": analysis.get("sub_scores", {}) or {},
        "gap_analysis": analysis.get("gap_analysis", []) or analysis.get("gaps", []) or [],
        "strengths": analysis.get("hits", []) or analysis.get("strengths", []) or [],
        "evidence": analysis.get("evidence", []) or [],
        "recommendation": analysis.get("decision", "N/A"),
        "verdict": analysis.get("verdict", {}) or {},
        "contact_ids": [],
    }
    saved_job = _pgr_insert(token, "jobs", job, warnings=schema_warn)

    # --- recruiter persistence hardening (CHG-023) -------------------------
    # The manual contact wins when the client filled any of its fields; a
    # PARTIAL contact (name-only, phone-only, email-only...) is preserved, not
    # dropped. When the client sent nothing but the JD itself named an
    # individual recruiter (parsed_job.recruiter_contact), AIROS persists that
    # recruiter server-side so an "RH defined in JD" is never silently lost.
    contact_data = req.contact
    if not (contact_data and _contact_filled(contact_data)):
        parsed_rc = parsed.get("recruiter_contact") or {}
        if isinstance(parsed_rc, dict) and _rc_filled(parsed_rc):
            contact_data = ContactIn(
                name=str(parsed_rc.get("name") or "").strip(),
                position=str(parsed_rc.get("position") or "").strip(),
                email=str(parsed_rc.get("email") or "").strip(),
                phone=str(parsed_rc.get("phone") or "").strip(),
                linkedin_url=str(parsed_rc.get("linkedin_url") or "").strip(),
                contact_type="HR Recruiter",
                source="JD",
                confidence="High" if str(parsed_rc.get("email") or "").strip() else "Medium",
            )
    contact = None
    if contact_data and _contact_filled(contact_data):
        contact = _create_contact(
            token, account_id, company["company_id"], contact_data,
            warnings=schema_warn,
        )
        _pgr_update(token, "jobs", {
            "account_id": f"eq.{account_id}", "job_id": f"eq.{saved_job['job_id']}"
        }, {"contact_ids": [contact["contact_id"]]}, warnings=schema_warn)
        saved_job["contact_ids"] = [contact["contact_id"]]

    result: Dict[str, Any] = {"job": saved_job, "company": company, "contact": contact}
    if schema_warn:
        result["schema_warning"] = " ".join(schema_warn)
    return result


@router.post("/jobs/{job_id}/contacts")
def add_contact_to_job(
    job_id: str,
    contact: ContactIn,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    job = _get_job(token, account_id, job_id)
    schema_warn: List[str] = []
    created = _create_contact(
        token, account_id, job["company_id"], contact, warnings=schema_warn
    )
    linked = list(job.get("contact_ids") or []) + [created["contact_id"]]
    _pgr_update(token, "jobs", {
        "account_id": f"eq.{account_id}", "job_id": f"eq.{job_id}"
    }, {"contact_ids": linked}, warnings=schema_warn)
    result: Dict[str, Any] = {"contact": created, "contact_ids": linked}
    if schema_warn:
        result["schema_warning"] = " ".join(schema_warn)
    return result


# =============================================================================
# Stage 2 - Document Engine (ONE Gemini call) + post-generation validation
# =============================================================================
_DOCUMENT_MIME = {
    "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def _generated_folder(owner_sub: str, job_id: str) -> Path:
    """protected/<account>/generated/<job> - ISS-006: content stays off the DB."""
    return _account_dir(owner_sub) / "generated" / re.sub(r"[^A-Za-z0-9_-]", "_", job_id)


def _save_generated_document(
    owner_sub: str, job_id: str, doc_type: str, content: str,
    extension: str = "txt", timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist generated TEXT to the protected local store (V2 parity)."""
    stamp = timestamp or lc.now_iso().replace(":", "").replace("-", "")
    return _save_generated_document_bytes(
        owner_sub, job_id, doc_type, content.encode("utf-8"), extension, stamp
    )


def _save_generated_document_bytes(
    owner_sub: str, job_id: str, doc_type: str, content: bytes,
    extension: str, timestamp: str,
) -> Dict[str, Any]:
    """Persist one rendition (txt/docx/pdf) to the protected local store.

    All renditions of one generated document share the SAME timestamp stem
    (`<doc_type>_<stamp>.<ext>`), so the download endpoint can resolve a
    rendition from the canonical text document_id without a schema change.
    """
    folder = _generated_folder(owner_sub, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{doc_type}_{timestamp}.{extension}"
    filepath = folder / filename
    filepath.write_bytes(content)
    size_kb = round(len(content) / 1024, 1)
    return {
        "original_name": filename,
        "saved_as": filename,
        "path": str(filepath),
        "storage_ref": f"local://{filepath.as_posix()}",
        "size_kb": size_kb,
        "mime": _DOCUMENT_MIME.get(extension, "application/octet-stream"),
    }


def _render_documents(
    generated: Dict[str, Any],
    profile: Dict[str, Any],
    job: Dict[str, Any],
    owner_sub: str,
    job_id: str,
    timestamp: str,
) -> Dict[str, Any]:
    """Render the generated content into professional DOCX (+ PDF) renditions.

    CHG-026 pipeline: structured model -> schema validation -> deterministic
    python-docx render -> content-integrity QA -> protected store -> optional
    LibreOffice headless PDF.

    ISOLATION GUARANTEE (guide section 10): this runs AFTER the generated text
    was persisted, and ANY failure here is only RECORDED in the returned
    report - it never raises, never regenerates AI content, and never blocks
    the workspace (the .txt documents and the on-screen text remain usable).
    """
    report: Dict[str, Any] = {
        "pdf_available": libreoffice_available(),
        "documents": {},
        "errors": [],
    }
    payloads: List[tuple[str, Any]] = []
    cv_data = generated.get("cv") or {}
    if isinstance(cv_data, dict) and (str(cv_data.get("summary") or "").strip() or cv_data.get("experience")):
        payloads.append(("cv", build_cv_document(cv_data, profile, meta={"job_id": job_id})))
    letter_data = generated.get("cover_letter") or {}
    if isinstance(letter_data, dict) and any(
        str(letter_data.get(key) or "").strip() for key in ("opening", "body", "greeting")
    ):
        payloads.append((
            "cover_letter",
            build_cover_letter_document(letter_data, profile, job, meta={"job_id": job_id}),
        ))

    for doc_type, model in payloads:
        entry: Dict[str, Any] = {"ok": False, "errors": []}
        report["documents"][doc_type] = entry
        try:
            schema = validate_document_model(model)
            entry["errors"] += [f"schema: {message}" for message in schema["errors"]]
            if not schema["ok"]:
                report["errors"].append(f"{doc_type}: schema invalid")
                continue
            docx_bytes = render_document(model)
            qa = validate_rendered_document(model, docx_bytes)
            entry["ok"] = bool(qa["ok"])
            entry["errors"] += qa["errors"]
            docx_meta = _save_generated_document_bytes(
                owner_sub, job_id, doc_type, docx_bytes, "docx", timestamp,
            )
            entry["docx"] = {
                "saved_as": docx_meta["saved_as"],
                "storage_ref": docx_meta["storage_ref"],
                "size_kb": docx_meta["size_kb"],
            }
            if libreoffice_available():
                try:
                    pdf_path = convert_docx_to_pdf(Path(docx_meta["path"]))
                    pdf_meta = _save_generated_document_bytes(
                        owner_sub, job_id, doc_type, pdf_path.read_bytes(), "pdf", timestamp,
                    )
                    entry["pdf"] = {
                        "saved_as": pdf_meta["saved_as"],
                        "storage_ref": pdf_meta["storage_ref"],
                        "size_kb": pdf_meta["size_kb"],
                    }
                except PdfConversionError as exc:
                    entry["errors"].append(f"pdf: {exc}")
            else:
                entry["errors"].append(
                    "pdf: LibreOffice is not available on the server - the PDF was skipped "
                    "(the DOCX is ready; the PDF appears automatically once LibreOffice is installed)"
                )
        except Exception as exc:  # noqa: BLE001 - rendering must never break generation
            entry["ok"] = False
            entry["errors"].append(f"render: {exc}")
            report["errors"].append(f"{doc_type}: {exc}")
    return report


@router.post("/jobs/{job_id}/documents")
def generate_documents(
    job_id: str,
    req: DocumentsRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    api_key = _gemini_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY missing on the server.")

    account_id = _account_id(token)
    job = _get_job(token, account_id, job_id)
    profile = _fetch_own_profile(token)
    if not profile:
        raise HTTPException(status_code=409, detail="No profile found. Build your profile first.")

    company_rows = _pgr_get(token, "companies", {
        "select": "*", "account_id": f"eq.{account_id}",
        "company_id": f"eq.{job['company_id']}", "limit": "1",
    })
    company = company_rows[0] if company_rows else {}

    contact_ids = job.get("contact_ids") or []
    contacts = []
    if contact_ids:
        contacts = _pgr_get(token, "contacts", {
            "select": "*", "account_id": f"eq.{account_id}",
            "contact_id": f"in.({','.join(contact_ids)})",
        })

    candidate = build_candidate_json(profile)
    try:
        generated = generate_application_documents(
            candidate, job, company, contacts, api_key,
            generate_cv=req.generate_cv,
            generate_cover_letter=req.generate_cover_letter,
            generate_recruiter_email=req.generate_recruiter_email,
        )
    except GatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    validation = validate_generated_documents(generated, job, candidate)

    reliable = generated.get("recruiter_contact") or find_reliable_contact(contacts)
    generated_at = lc.now_iso()
    # One timestamp stem for EVERY rendition (txt/docx/pdf) of this generation
    # run, so the download endpoint can resolve renditions per document.
    rendition_stamp = generated_at.replace(":", "").replace("-", "")

    # Persist the exact system datetime of the document generation on the job
    # so the workspace approval + later confirm can compute accurate durations
    # (CHG-023; jobs.docs_generated_at from migration 0008).
    _pgr_update(token, "jobs", {
        "account_id": f"eq.{account_id}", "job_id": f"eq.{job_id}"
    }, {"docs_generated_at": generated_at})

    # Persist the generated documents to the protected local store (ISS-006:
    # content stays OUT of the DB) + metadata-only documents rows.
    docs_meta: Dict[str, Any] = {}
    doc_payloads = [
        ("cv", (generated.get("cv") or {}).get("full_text", "") or ""),
        ("cover_letter", (generated.get("cover_letter") or {}).get("full_text", "") or ""),
    ]
    email = generated.get("recruiter_email") or {}
    if email.get("required") and email.get("body"):
        doc_payloads.append(("recruiter_email",
                             f"Subject: {email.get('subject', '')}\n\n{email.get('body', '')}"))
    for doc_type, content in doc_payloads:
        if not content.strip():
            continue
        meta = _save_generated_document(str(claims["sub"]), job_id, doc_type, content, timestamp=rendition_stamp)
        row = _pgr_insert(token, "documents", {
            "account_id": account_id,
            "original_name": meta["original_name"],
            "saved_as": meta["saved_as"],
            "uploaded_at": generated_at,
            "size_kb": meta["size_kb"],
            "mime": meta["mime"],
            "storage_ref": meta["storage_ref"],
        })
        docs_meta[f"{doc_type}_path"] = meta["storage_ref"]
        docs_meta[f"{doc_type}_document_id"] = row.get("id")
        if doc_type == "recruiter_email":
            # Key parity: the frontend PrepareTab and _latest_job_documents()
            # use the short 'email_*' keys for the recruiter email.
            docs_meta["email_path"] = meta["storage_ref"]
            docs_meta["email_document_id"] = row.get("id")

    # CHG-026: render the SAME approved content into professional DOCX (+ PDF)
    # renditions. Failures are recorded, never raised - content generation and
    # rendering stay strictly separated (guide section 10).
    rendering = _render_documents(
        generated, profile, job, str(claims["sub"]), job_id, rendition_stamp,
    )

    return {
        "job_id": job_id,
        "generated": generated,
        "validation": validation,
        "reliable_contact": reliable or {},
        # Explicit non-blocking RH signal: no reliable individual recruiter
        # email -> the recruiter email is skipped, the document generation
        # (CV + cover letter) is NOT blocked (manual-test feedback, Sep 2026).
        "recruiter_email_skipped": not bool(reliable),
        "docs": docs_meta,
        "docs_generated_at": generated_at,
        "rendering": rendering,
    }


# =============================================================================
# Stage 2 (end) - Confirm Application (V2 verbatim semantics)
# =============================================================================
def _latest_job_documents(token: str, account_id: str, job_id: str) -> Dict[str, Any]:
    """The most recent generated documents for a job (documents table, RLS)."""
    rows = _pgr_get(token, "documents", {
        "select": "id,saved_as,storage_ref,uploaded_at",
        "account_id": f"eq.{account_id}",
        "storage_ref": f"like.local://*generated/{job_id}*",
        "order": "uploaded_at.desc",
        "limit": "20",
    })
    docs: Dict[str, Any] = {}
    for row in rows or []:
        ref = row.get("storage_ref", "")
        name = row.get("saved_as", "")
        if name.startswith("cv_"):
            docs.setdefault("cv_path", ref)
            docs.setdefault("cv_document_id", row.get("id"))
        elif name.startswith("cover_letter_"):
            docs.setdefault("cover_letter_path", ref)
            docs.setdefault("cover_letter_document_id", row.get("id"))
        elif name.startswith("recruiter_email_"):
            docs.setdefault("email_path", ref)
            docs.setdefault("email_document_id", row.get("id"))
    # generated_at = newest uploaded_at across the job's generated docs
    # (drives docs_generated_at + time_consumed_min; was always "" before).
    stamps = [str(r.get("uploaded_at") or "") for r in (rows or [])]
    stamps = [s for s in stamps if s]
    if stamps:
        docs["generated_at"] = sorted(stamps, reverse=True)[0]
    return docs


# -------------------------------------------------------------------------
# Workspace approval + saved-jobs listing (CHG-023 application workspace)
# -------------------------------------------------------------------------
@router.post("/jobs/{job_id}/documents/approve")
def approve_documents(
    job_id: str,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    """User approval gate: persist the EXACT system datetime of the approval
    (jobs.docs_approved_at) so the later Confirm can compute accurate duration
    metrics (time consumed between document finalization and submission)."""
    account_id = _account_id(token)
    job = _get_job(token, account_id, job_id)
    approved_at = lc.now_iso()
    generated_at = job.get("docs_generated_at") or ""
    if not generated_at:
        docs = _latest_job_documents(token, account_id, job_id)
        generated_at = docs.get("generated_at", "") or approved_at
    _pgr_update(token, "jobs", {
        "account_id": f"eq.{account_id}", "job_id": f"eq.{job_id}"
    }, {"docs_approved_at": approved_at, "docs_generated_at": generated_at})
    return {
        "job_id": job_id,
        "docs_generated_at": generated_at,
        "docs_approved_at": approved_at,
        "time_consumed_min": lc.minutes_between(generated_at, approved_at),
    }


@router.get("/jobs")
def list_saved_jobs(
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    """Saved jobs for the Application Workspace picker (newest analysis first)."""
    account_id = _account_id(token)
    rows = _pgr_get(token, "jobs", {
        "select": "*", "account_id": f"eq.{account_id}",
        "order": "analysis_date.desc.nullslast,created_at.desc",
    })
    return {"jobs": rows or []}


@router.get("/jobs/{job_id}")
def job_workspace_detail(
    job_id: str,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    """Application Workspace detail: job + company + recruiter(s) + generated
    docs + workspace timestamps (docs_generated_at / docs_approved_at)."""
    account_id = _account_id(token)
    job = _get_job(token, account_id, job_id)

    company_rows = _pgr_get(token, "companies", {
        "select": "*", "account_id": f"eq.{account_id}",
        "company_id": f"eq.{job['company_id']}", "limit": "1",
    })
    company = company_rows[0] if company_rows else {}

    contacts = []
    if job.get("contact_ids"):
        contacts = _pgr_get(token, "contacts", {
            "select": "*", "account_id": f"eq.{account_id}",
            "contact_id": f"in.({','.join(job['contact_ids'])})",
        })
    reliable = find_reliable_contact(contacts) or {}
    contact = reliable or (contacts[0] if contacts else None)

    docs = _latest_job_documents(token, account_id, job_id)
    generated_at = job.get("docs_generated_at") or docs.get("generated_at", "") or ""
    approved_at = job.get("docs_approved_at") or ""

    return {
        "job": job,
        "company": company,
        "contact": contact,
        "contacts": contacts,
        "docs": docs,
        "docs_generated_at": generated_at,
        "docs_approved_at": approved_at,
    }


@router.post("")
def confirm_application(
    req: ConfirmApplicationRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    if req.decision not in ("sent", "cancelled"):
        raise HTTPException(status_code=422, detail='decision must be "sent" or "cancelled"')
    if req.decision == "cancelled":
        # V2: "Cancelled / Not sent" -> NO tracking record is created.
        return {"created": False, "application_id": ""}

    if not req.channel:
        raise HTTPException(status_code=422, detail="Application channel is required")

    account_id = _account_id(token)
    job = _get_job(token, account_id, req.job_id)

    contact_ids = job.get("contact_ids") or []
    reliable = {}
    if contact_ids:
        contacts = _pgr_get(token, "contacts", {
            "select": "*", "account_id": f"eq.{account_id}",
            "contact_id": f"in.({','.join(contact_ids)})",
        })
        reliable = find_reliable_contact(contacts) or {}

    company_rows = _pgr_get(token, "companies", {
        "select": "name", "account_id": f"eq.{account_id}",
        "company_id": f"eq.{job['company_id']}", "limit": "1",
    })
    company_name = (company_rows[0].get("name") if company_rows else "") or ""

    docs = _latest_job_documents(token, account_id, req.job_id)
    # Exact system datetimes of the workspace (migration 0008): the job row
    # captured them at generation/approval time so durations are accurate even
    # when the user confirms much later.
    docs_generated_at = job.get("docs_generated_at") or docs.get("generated_at", "") or ""
    docs_approved_at = job.get("docs_approved_at") or ""
    app_ids = [r["application_id"] for r in _pgr_get(token, "applications", {
        "select": "application_id", "account_id": f"eq.{account_id}"
    })]
    record = lc.create_application_record(
        lc.next_sequential_id("APP", app_ids),
        job,
        company_name=company_name,
        channel=req.channel,
        application_date=req.application_date or None,
        notes=req.notes,
        recruiter=reliable,
        docs=docs,
        docs_generated_at=docs_generated_at,
        docs_approved_at=docs_approved_at,
    )
    row = {
        "account_id": account_id,
        "application_id": record["application_id"],
        "job_id": record["job_id"],
        "company_id": record["company_id"],
        "title": record["title"],
        "status": record["status"],
        "application_date": record["application_date"],
        "ats_score": record["ats_score"],
        "time_consumed_min": record["time_consumed_min"],
        "recruiter_id": record["recruiter_id"],
        "recruiter_name": record["recruiter_name"],
        "recruiter_email": record["recruiter_email"],
        "outcome": record["outcome"],
        "outcome_detail": record["outcome_detail"],
        "timeline": record["timeline"],
        "interviews": record["interviews"],
        "recruiter_interactions": record["recruiter_interactions"],
        "recruiter_responses": record["recruiter_responses"],
        "follow_ups": record["follow_ups"],
        "assessment": record["assessment"],
        "cv_version": record["cv_version"],
        "cover_letter_version": record["cover_letter_version"],
        "recruiter_email_path": record["recruiter_email_path"],
        "channel": record["channel"],
        "notes": record["notes"],
        "docs_generated_at": record["docs_generated_at"],
        "docs_approved_at": record.get("docs_approved_at", ""),
        "company_name": record["company_name"],
        "location": record["location"],
        "country": record["country"],
        "job_url": record["job_url"],
        "source": record["source"],
        "recruiter_position": reliable.get("position", ""),
        "recruiter_linkedin": reliable.get("linkedin_url", ""),
        "last_activity": record["last_activity"],
        "last_activity_at": record["last_activity_at"],
        "follow_up_checkpoint": record["follow_up_checkpoint"],
        "employer_response_date": record["employer_response_date"],
        "job_closing_date": record["job_closing_date"],
        "next_action_source": record["next_action_source"],
    }
    saved = _pgr_insert(token, "applications", row)
    return {"created": True, "application_id": record["application_id"], "application": saved}


# =============================================================================
# Stage 3 - Job Tracking (V2 page 5 parity; manual-only transitions)
# =============================================================================
def _apply_and_persist(
    token: str, account_id: str, application_id: str, mutate
) -> Dict[str, Any]:
    """Load the RLS-scoped row, apply the pure lifecycle function, persist it."""
    row = _get_application(token, account_id, application_id)
    app = dict(row)
    mutate(app)
    patch = {
        "status": app["status"],
        "outcome": app.get("outcome", ""),
        "outcome_detail": app.get("outcome_detail"),
        "timeline": app.get("timeline", []),
        "interviews": app.get("interviews", []),
        "recruiter_interactions": app.get("recruiter_interactions", []),
        "recruiter_responses": app.get("recruiter_responses", []),
        "follow_ups": app.get("follow_ups", []),
        "assessment": app.get("assessment"),
        "last_activity": app.get("last_activity", ""),
        "last_activity_at": app.get("last_activity_at", ""),
        "follow_up_checkpoint": app.get("follow_up_checkpoint", ""),
        "employer_response_date": app.get("employer_response_date", ""),
        "job_closing_date": app.get("job_closing_date", ""),
        "next_action_source": app.get("next_action_source", ""),
        "notes": app.get("notes", ""),
    }
    updated = _pgr_update(token, "applications", {
        "account_id": f"eq.{account_id}", "application_id": f"eq.{application_id}"
    }, patch)
    detail = dict(updated or app)
    detail["allowed_transitions"] = lc.get_valid_transitions(detail.get("status", lc.APPLIED))
    detail["next_action"] = lc.next_action(detail)
    detail["pending_interview"] = lc.find_pending_interview(detail)
    return detail


def _lifecycle_value_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/{application_id}")
def application_detail(
    application_id: str,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    app = dict(_get_application(token, account_id, application_id))
    # Enrich with the RH + company context the Track UI renders (V2 page 5):
    # linked job row (contact_ids), the reliable recruiter contact, and the
    # full company card. All reads stay RLS-scoped via the caller's token.
    try:
        job_rows = _pgr_get(token, "jobs", {
            "select": "*", "account_id": f"eq.{account_id}",
            "job_id": f"eq.{app.get('job_id', '')}", "limit": "1",
        })
        job = job_rows[0] if job_rows else {}
        contact_ids = list(job.get("contact_ids") or [])
        contacts: List[Dict[str, Any]] = []
        if contact_ids:
            contacts = _pgr_get(token, "contacts", {
                "select": "*", "account_id": f"eq.{account_id}",
                "contact_id": f"in.({','.join(contact_ids)})",
            }) or []
        reliable = find_reliable_contact(contacts) or {}
        company_rows = _pgr_get(token, "companies", {
            "select": "*", "account_id": f"eq.{account_id}",
            "company_id": f"eq.{app.get('company_id', '')}", "limit": "1",
        })
        app["job"] = job
        app["contacts"] = contacts
        app["reliable_contact"] = reliable
        app["company"] = company_rows[0] if company_rows else {}
    except Exception:
        app.setdefault("job", {})
        app.setdefault("contacts", [])
        app.setdefault("reliable_contact", {})
        app.setdefault("company", {})
    app["allowed_transitions"] = lc.get_valid_transitions(app.get("status", lc.APPLIED))
    app["next_action"] = lc.next_action(app)
    app["pending_interview"] = lc.find_pending_interview(app)
    app["follow_up_draft"] = lc.draft_follow_up(app)
    return {"application": app}


@router.post("/{application_id}/status")
def update_status(
    application_id: str,
    req: StatusRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.update_status_record(app, req.new_status, req.note),
        )}
    except lc.TransitionError as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/response")
def record_response(
    application_id: str,
    req: ResponseRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.record_employer_response_record(
                app, req.response_type, req.channel, req.responded_on, req.note),
        )}
    except (lc.TransitionError, ValueError) as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/interview")
def schedule_interview(
    application_id: str,
    req: InterviewRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.schedule_interview_record(
                app, req.round_no, req.scheduled_at, req.mode, req.notes),
        )}
    except ValueError as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/followup")
def record_follow_up(
    application_id: str,
    req: FollowUpRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.mark_contacted_record(app, req.contacted_at, req.channel, req.note),
        )}
    except lc.TransitionError as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/remind-later")
def remind_me_later(
    application_id: str,
    req: RemindLaterRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    return {"application": _apply_and_persist(
        token, account_id, application_id,
        lambda app: lc.remind_me_later_record(app, req.days),
    )}


@router.post("/{application_id}/response-date")
def set_response_date(
    application_id: str,
    req: DateRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.set_employer_response_date_record(app, req.date),
        )}
    except ValueError as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/closing-date")
def set_closing_date(
    application_id: str,
    req: DateRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.set_job_closing_date_record(app, req.date),
        )}
    except ValueError as exc:
        raise _lifecycle_value_error(exc) from exc


@router.post("/{application_id}/close")
def close_application(
    application_id: str,
    req: CloseRequest,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> dict:
    account_id = _account_id(token)
    try:
        return {"application": _apply_and_persist(
            token, account_id, application_id,
            lambda app: lc.close_application_record(app, req.note),
        )}
    except lc.TransitionError as exc:
        raise _lifecycle_value_error(exc) from exc


# =============================================================================
# Generated-document download (auth-gated; ownership checked via RLS read)
# =============================================================================
@router.get("/documents/{document_id}/content")
def document_content(
    document_id: str,
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> PlainTextResponse:
    account_id = _account_id(token)
    rows = _pgr_get(token, "documents", {
        "select": "id,saved_as,storage_ref",
        "account_id": f"eq.{account_id}", "id": f"eq.{document_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    ref = rows[0].get("storage_ref", "")
    if not ref.startswith("local://"):
        raise HTTPException(status_code=409, detail="Document is not in the local store.")
    path = Path(ref[len("local://"):])
    if not path.exists():
        raise HTTPException(status_code=410, detail="Document content is gone from the local store.")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: str,
    file_format: str = Query("docx", alias="format"),
    claims: dict = Depends(current_claims),
    token: str = Depends(bearer_token),
) -> FileResponse:
    """Auth-gated RENDITION download (DOCX | PDF) for one generated document.

    The canonical `documents` row stays the text document (metadata-only per
    ISS-006); the rendered renditions share its timestamp stem in the same
    protected folder (`<doc_type>_<stamp>.<ext>`), so no schema change was
    needed and ownership still resolves through the same RLS-scoped read.
    """
    fmt = (file_format or "").lower().lstrip(".")
    if fmt not in _DOCUMENT_MIME or fmt == "txt":
        raise HTTPException(status_code=422, detail="format must be 'docx' or 'pdf'.")
    account_id = _account_id(token)
    rows = _pgr_get(token, "documents", {
        "select": "id,saved_as,storage_ref",
        "account_id": f"eq.{account_id}", "id": f"eq.{document_id}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    ref = rows[0].get("storage_ref", "")
    if not ref.startswith("local://"):
        raise HTTPException(status_code=409, detail="Document is not in the local store.")
    text_path = Path(ref[len("local://"):])
    if not text_path.exists():
        raise HTTPException(status_code=410, detail="Document content is gone from the local store.")
    rendition = text_path.with_suffix("." + fmt)
    if not rendition.exists():
        hint = (
            "Install LibreOffice on the server (free) to enable PDF conversion - "
            "the DOCX is available."
            if fmt == "pdf"
            else "Re-generate the documents to create the DOCX rendition."
        )
        raise HTTPException(
            status_code=409,
            detail=f"The {fmt.upper()} rendition is not available for this document. {hint}",
        )
    return FileResponse(
        rendition,
        media_type=_DOCUMENT_MIME[fmt],
        filename=rendition.name,
        content_disposition_type="attachment",
    )

