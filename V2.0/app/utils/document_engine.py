# app/utils/document_engine.py
"""
AIROS Document Engine
Single Gemini call that produces structured CV + Cover Letter + (optional) Recruiter Email.

Per specification Step 8, the single Gemini generation call receives:
- Candidate JSON
- Job JSON
- ATS Analysis
- Gap Analysis
- Evidence Matrix
- Target CV Profile
- Company Information
- Recruiter Information
- Generation Rules
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional
import streamlit as st

from utils.ats import _call_gemini, _clean_json_response, build_candidate_json
from utils.job import get_job
from utils.company import _get_companies, get_company
from utils.contact import get_contact


def _get_company(company_id: str) -> Dict[str, Any]:
    return _get_companies().get(company_id, {}) or get_company(company_id) or {}


def generate_application_documents(
    job_id: str,
    generate_cv: bool = True,
    generate_cover_letter: bool = True,
    generate_recruiter_email: bool = True,
) -> Dict[str, Any]:
    """
    Main entry point of the Document Engine.
    Returns the structured JSON defined in the specification (Step 10).
    """
    job = get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    candidate = build_candidate_json()
    company = _get_company(job.get("company_id", ""))
    parsed_job = job.get("job_json") or {}

    # Find reliable recruiter if requested
    reliable_contact = None
    if generate_recruiter_email:
        for cid in job.get("contact_ids", []):
            contact = get_contact(cid)
            if not contact:
                continue
            email = (contact.get("email") or "").lower()
            if not email:
                continue
            if contact.get("confidence") not in ("High", "Medium"):
                continue
            if any(email.startswith(p) for p in ("info@", "contact@", "careers@", "jobs@", "hr@", "hello@", "recruitment@")):
                continue
            reliable_contact = contact
            break

    # Build the single comprehensive prompt with ALL inputs per spec
    prompt = _build_generation_prompt(
        candidate=candidate,
        job=job,
        parsed_job=parsed_job,
        company=company,
        reliable_contact=reliable_contact,
        generate_cv=generate_cv,
        generate_cover_letter=generate_cover_letter,
        generate_recruiter_email=bool(reliable_contact) and generate_recruiter_email,
    )

    raw = _call_gemini(prompt, json_mode=True)

    if not raw:
        return {"error": "Gemini call failed"}

    try:
        cleaned = _clean_json_response(raw)
        data = json.loads(cleaned)
    except Exception as e:
        return {"error": f"Failed to parse Gemini response: {e}", "raw": raw[:1000]}

    # Safety: force recruiter_email.required = false if no reliable contact (Step 9)
    if not reliable_contact:
        data["recruiter_email"] = {
            "required": False,
            "to": "",
            "subject": "",
            "body": "",
            "message": "No reliable individual recruiter email was identified. Recruiter email was not generated."
        }

    return data


def _build_generation_prompt(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    parsed_job: Dict[str, Any],
    company: Dict[str, Any],
    reliable_contact: Optional[Dict[str, Any]],
    generate_cv: bool,
    generate_cover_letter: bool,
    generate_recruiter_email: bool,
) -> str:
    """Construct the single comprehensive prompt with all specification inputs."""

    # ------------------------------------------------------------------
    # Input 1: Candidate JSON
    # ------------------------------------------------------------------
    candidate_str = json.dumps(candidate, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 2: Job JSON
    # ------------------------------------------------------------------
    job_str = json.dumps(parsed_job, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 3: ATS Analysis (full)
    # ------------------------------------------------------------------
    ats_score = job.get("ats_score", 0)
    recommendation = job.get("recommendation", "")
    ats_components = job.get("ats_components", {})
    ats_analysis_str = json.dumps({
        "score": ats_score,
        "recommendation": recommendation,
        "components": ats_components,
    }, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 4: Gap Analysis (structured)
    # ------------------------------------------------------------------
    gaps = job.get("gap_analysis", [])
    strengths = job.get("strengths", [])
    gap_analysis_str = json.dumps({
        "missing": gaps,
        "strengths": strengths,
    }, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 5: Evidence Matrix
    # ------------------------------------------------------------------
    evidence = job.get("evidence", [])
    evidence_str = json.dumps(evidence, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 6: Target CV Profile (candidate's base profile to adapt)
    # ------------------------------------------------------------------
    target_cv_profile_str = json.dumps({
        "personal_identity": candidate.get("personal_identity", {}),
        "career_stage": candidate.get("career_stage", ""),
        "education": candidate.get("education", []),
        "experience": candidate.get("experience", []),
        "skills": candidate.get("skills", {}),
        "languages": candidate.get("languages", []),
        "certifications": candidate.get("certifications", []),
        "total_experience_years": candidate.get("total_experience_years", 0),
        "location": candidate.get("location", ""),
        "nationality": candidate.get("nationality", ""),
        "industry_hints": candidate.get("industry_hints", []),
    }, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 7: Company Information
    # ------------------------------------------------------------------
    company_str = json.dumps(company, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 8: Recruiter Information
    # ------------------------------------------------------------------
    contact_str = json.dumps(reliable_contact or {}, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Input 9: Generation Rules
    # ------------------------------------------------------------------
    rules_str = (
        "1. Optimize for ATS relevance using the Job JSON as the target.\n"
        "2. Prioritize required skills over preferred skills.\n"
        "3. Use candidate evidence from the Evidence Matrix — never claim a skill with level 0 (missing).\n"
        "4. Use relevant terminology and legitimate synonyms.\n"
        "5. Quantify achievements only where evidence exists.\n"
        "6. Preserve complete truthfulness.\n"
        "7. Never fabricate skills, experience, employers, certifications, education or achievements.\n"
        "8. Never convert a missing requirement into a claimed skill.\n"
        "9. Adapt the CV to the specific Job.\n"
        "10. Adapt the Cover Letter to the specific Company and Job."
    )

    return f"""
You are an elite executive career coach and ATS optimization specialist.
Your task is to generate application documents that are truthful, evidence-based and highly relevant to the target job.

=== GENERATION RULES (MUST FOLLOW) ===
{rules_str}

=== OUTPUT FORMAT (strict JSON — Step 10 of spec) ===
Return ONLY valid JSON with this exact structure:

{{
  "cv": {{
    "summary": "",
    "experience": [],
    "skills": {{
      "technical": [],
      "methodologies": [],
      "tools": []
    }},
    "education": [],
    "certifications": [],
    "languages": [],
    "full_text": ""
  }},
  "cover_letter": {{
    "greeting": "",
    "opening": "",
    "body": "",
    "closing": "",
    "full_text": ""
  }},
  "recruiter_email": {{
    "required": true,
    "to": "",
    "subject": "",
    "body": ""
  }},
  "optimization_report": {{
    "target_keywords_used": [],
    "strengths_emphasized": [],
    "gaps_not_claimed": [],
    "evidence_based": true
  }}
}}

=== GENERATION FLAGS ===
- Generate CV section: {generate_cv}
- Generate Cover Letter section: {generate_cover_letter}
- Generate Recruiter Email: {generate_recruiter_email}

If a section is not requested, still return the key but with empty content.

=== INPUT 1: CANDIDATE JSON (full candidate data) ===
{candidate_str}

=== INPUT 2: JOB JSON (the target job) ===
{job_str}

=== INPUT 3: ATS ANALYSIS ===
{ats_analysis_str}

=== INPUT 4: GAP ANALYSIS (structured) ===
{gap_analysis_str}

=== INPUT 5: EVIDENCE MATRIX (per-skill star ratings) ===
{evidence_str}

=== INPUT 6: TARGET CV PROFILE (the base profile to adapt — use ONLY this data) ===
{target_cv_profile_str}

=== INPUT 7: COMPANY INFORMATION ===
{company_str}

=== INPUT 8: RECRUITER INFORMATION (only use if present and reliable) ===
{contact_str}

=== INSTRUCTIONS PER DOCUMENT ===

1. TAILORED CV
- Rewrite the professional summary to match the job using the Target CV Profile.
- Re-order and rephrase experience bullets to highlight the most relevant achievements.
- Put the most relevant skills first (use the Evidence Matrix).
- Emphasize skills with ★★★★☆ or ★★★★★.
- Do NOT claim skills with ☆☆☆☆☆ (missing) as if the candidate has them.
- Keep the full_text as a clean, ready-to-use plain text version of the CV.

2. COVER LETTER
- Address the company and role specifically (use the Company Information).
- Reference 2-3 strongest matching points from the candidate profile (use the Evidence Matrix).
- Keep a professional, confident tone.
- Provide both structured fields and a complete full_text.

3. RECRUITER EMAIL (only if required = true)
- Formal, concise, professional.
- Subject must be clear and specific.
- Body should be short (max 180 words).
- Include a polite call to action.

4. OPTIMIZATION REPORT
- List the key job keywords you intentionally used.
- List the candidate strengths you emphasized.
- Explicitly list the gaps you refused to claim.
- Set evidence_based = true only if you respected all truthfulness rules.

Now generate the documents.
"""