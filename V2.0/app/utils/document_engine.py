# app/utils/document_engine.py
"""
AIROS Document Engine
Single Gemini call that produces structured CV + Cover Letter + (optional) Recruiter Email.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional
import streamlit as st

from utils.ats import _call_gemini, _clean_json_response, build_candidate_json
from utils.job import get_job
from utils.company import _get_companies
from utils.contact import get_contact


def _get_company(company_id: str) -> Dict[str, Any]:
    return _get_companies().get(company_id, {})


def generate_application_documents(
    job_id: str,
    generate_cv: bool = True,
    generate_cover_letter: bool = True,
    generate_recruiter_email: bool = True,
) -> Dict[str, Any]:
    """
    Main entry point of the Document Engine.
    Returns the structured JSON defined in the specification.
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

    # Build the big prompt
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

    # Safety: force recruiter_email.required = false if no reliable contact
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
    """Construct the single comprehensive prompt."""

    candidate_str = json.dumps(candidate, indent=2, ensure_ascii=False)
    job_str = json.dumps(parsed_job, indent=2, ensure_ascii=False)
    company_str = json.dumps(company, indent=2, ensure_ascii=False)
    contact_str = json.dumps(reliable_contact or {}, indent=2, ensure_ascii=False)

    ats_score = job.get("ats_score", 0)
    strengths = job.get("strengths", [])
    gaps = job.get("gap_analysis", [])
    recommendation = job.get("recommendation", "")

    return f"""
You are an elite executive career coach and ATS optimization specialist.
Your task is to generate application documents that are truthful, evidence-based and highly relevant to the target job.

=== STRICT RULES (MUST FOLLOW) ===
1. NEVER fabricate skills, experience, employers, certifications, education or achievements.
2. NEVER turn a missing requirement into a claimed skill.
3. Only use information that exists in the Candidate JSON.
4. Prioritize required skills from the Job JSON.
5. Use legitimate synonyms and job-specific terminology.
6. Quantify achievements only when the candidate data supports it.
7. Preserve complete truthfulness.
8. Optimize for ATS keyword relevance without keyword stuffing.

=== OUTPUT FORMAT (strict JSON) ===
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

=== CONTEXT ===

CANDIDATE JSON:
{candidate_str}

JOB JSON:
{job_str}

COMPANY INFORMATION:
{company_str}

RECRUITER INFORMATION (only use if present and reliable):
{contact_str}

ATS ANALYSIS SUMMARY:
- Score: {ats_score}%
- Recommendation: {recommendation}
- Strengths: {strengths}
- Gaps (DO NOT claim these): {gaps}

=== INSTRUCTIONS PER DOCUMENT ===

1. TAILORED CV
- Rewrite the professional summary to match the job.
- Re-order and rephrase experience bullets to highlight the most relevant achievements.
- Put the most relevant skills first.
- Keep the full_text as a clean, ready-to-use plain text version of the CV.

2. COVER LETTER
- Address the company and role specifically.
- Reference 2-3 strongest matching points from the candidate profile.
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