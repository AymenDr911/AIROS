# app/utils/job.py
from datetime import datetime
from typing import Dict, Any, Optional, List
import streamlit as st

from utils.ids import generate_job_id
from utils.company import find_or_create_company
from utils.contact import create_contact


def _get_jobs() -> Dict[str, Dict[str, Any]]:
    """Return the jobs dictionary from session_state (lean storage)."""
    if "jobs" not in st.session_state:
        st.session_state.jobs = {}
    return st.session_state.jobs


def save_job(
    analysis_result: Dict[str, Any],
    original_jd: str,
    job_title: str = "",
    company_name: str = "",
    location: str = "",
    country: str = "",
    job_url: str = "",
    source: str = "Manual",
    department: str = "",
) -> Dict[str, Any]:
    """
    Persist a temporary ATS analysis as a formal Job record.
    Creates / reuses a Company automatically.
    Returns the full saved Job dictionary.
    """
    parsed = analysis_result.get("parsed_job") or {}

    # 1. Create or reuse Company
    company = find_or_create_company(
        name=company_name or parsed.get("company_name") or "Unknown Company",
        industry=parsed.get("industry", ""),
        city=parsed.get("city") or location or parsed.get("location", ""),
        country=country or parsed.get("country", ""),
        address=parsed.get("address", ""),
        website=parsed.get("company_website", ""),
        linkedin_url=parsed.get("company_linkedin", ""),
        phone=parsed.get("company_phone", ""),
    )

    # 2. Generate immutable Job ID
    job_id = generate_job_id()
    now = datetime.now().isoformat(timespec="seconds")

    # 3. Build the Job record exactly according to the specification
    job = {
        # Identity
        "job_id": job_id,                                      # Yes – unique immutable
        "candidate_id": st.session_state.get("candidate_id", "CAND-UNKNOWN"),
        "company_id": company["company_id"],

        # Core fields
        "title": job_title or parsed.get("job_title") or "Untitled Position",
        "department": department or parsed.get("department", ""),
        "location": location or parsed.get("location", ""),
        "country": country or parsed.get("country", ""),
        "job_url": job_url or parsed.get("job_url", ""),
        "source": source,

        # Content
        "original_jd": original_jd,
        "job_json": parsed,                                    # Structured Gemini output

        # Dates
        "publication_date": parsed.get("publication_date"),    # Optional
        "analysis_date": now[:10],                             # YYYY-MM-DD

        # ATS results
        "ats_score": analysis_result.get("ats_score", 0),
        "ats_components": analysis_result.get("sub_scores", {}),
        "gap_analysis": analysis_result.get("gaps", []),       # Missing / weak requirements
        "strengths": analysis_result.get("hits", []),          # Strong matches (top-level)
        "evidence": analysis_result.get("evidence", []),       # Evidence matrix with star ratings
        "recommendation": analysis_result.get("decision", "N/A"),

        # Relationships
        "contact_ids": [],                                     # Will be filled by add_contact_to_job

        # Audit
        "created_at": now,
        "updated_at": now,
    }

    # 4. Persist
    _get_jobs()[job_id] = job
    return job


def get_all_jobs() -> List[Dict[str, Any]]:
    """Return all saved jobs as a list (newest first)."""
    jobs = list(_get_jobs().values())
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a single job by ID."""
    return _get_jobs().get(job_id)


def add_contact_to_job(
    job_id: str,
    name: str = "",
    position: str = "",
    email: str = "",
    linkedin_url: str = "",
    contact_type: str = "HR Recruiter",
    source: str = "Manual",
    confidence: str = "Medium",
) -> Optional[Dict[str, Any]]:
    """
    Create a Contact and link it to an existing Job.
    Returns the created contact or None if job not found.
    """
    jobs = _get_jobs()
    job = jobs.get(job_id)
    if not job:
        return None

    contact = create_contact(
        company_id=job["company_id"],
        name=name,
        position=position,
        email=email,
        linkedin_url=linkedin_url,
        contact_type=contact_type,
        source=source,
        confidence=confidence,
    )

    # Link the contact to the job
    if "contact_ids" not in job:
        job["contact_ids"] = []
    job["contact_ids"].append(contact["contact_id"])
    job["updated_at"] = datetime.now().isoformat(timespec="seconds")

    return contact