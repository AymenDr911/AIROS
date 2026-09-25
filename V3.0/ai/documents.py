"""AIROS Document Engine (CHG-018) - port of V2 ``app/utils/document_engine.py``.

Single Gemini call that produces structured CV + Cover Letter + (optional)
Recruiter Email. Per the V2 specification (Step 8) the single generation call
receives: Candidate JSON, Job JSON, ATS Analysis, Gap Analysis, Evidence
Matrix, Target CV Profile, Company Information, Recruiter Information and the
Generation Rules.

V3 changes (integration rules only - the prompt is verbatim):
- ISS-004: the Gemini key is INJECTED by the caller (server env only).
- The caller passes already-loaded records (candidate / job / company /
  contacts) - no session-state or DB access inside the engine.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ai.gateway import GatewayError, _call_gemini, _clean_json_response

# Generic company inboxes are NEVER treated as individual recruiters (V2 rule).
GENERIC_EMAIL_PREFIXES = (
    "info@", "contact@", "careers@", "jobs@", "hr@", "hello@", "recruitment@"
)


def _json_safe(value: Any) -> Any:
    """Recursively coerce non-JSON Python values into JSON-serializable ones.

    Guard rails for the ONE place in the engine that hands raw in-memory
    objects (the candidate builder's helper fields) to ``json.dumps()``.
    Sets -> sorted lists (V2 parity: V2 stored all_tokens as sorted(...)),
    tuples -> lists. Any other JSON-native value passes through untouched.
    """
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def find_reliable_contact(contacts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """V2 reliable-contact detection: individual email + High/Medium confidence."""
    for contact in contacts or []:
        email = (contact.get("email") or "").lower()
        if not email:
            continue
        if contact.get("confidence") not in ("High", "Medium"):
            continue
        if any(email.startswith(p) for p in GENERIC_EMAIL_PREFIXES):
            continue
        return contact
    return None


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
    # JSON-safety guard: the candidate built by build_candidate_json() carries
    # internal helper fields; coerce any non-JSON value (set/tuple) so the
    # prompt serialization below can never crash the endpoint (regression:
    # "Object of type set is not JSON serializable").
    candidate = _json_safe(candidate)

    ats_analysis = {
        "overall_ats": job.get("ats_score", 0),
        "sub_scores": job.get("ats_components", {}) or {},
        "decision": job.get("recommendation", "N/A"),
    }
    gap_analysis = job.get("gap_analysis", []) or []
    evidence = job.get("evidence", []) or []
    target_cv_profile = candidate

    candidate_str = json.dumps(candidate, indent=2, ensure_ascii=False)
    job_str = json.dumps(
        {
            "job_id": job.get("job_id", ""),
            "title": job.get("title", ""),
            "company_id": job.get("company_id", ""),
            "location": job.get("location", ""),
            "country": job.get("country", ""),
            "job_url": job.get("job_url", ""),
            "parsed": parsed_job,
        },
        indent=2,
        ensure_ascii=False,
    )
    ats_analysis_str = json.dumps(ats_analysis, indent=2, ensure_ascii=False)
    gap_analysis_str = json.dumps(gap_analysis, indent=2, ensure_ascii=False)
    evidence_str = json.dumps(evidence, indent=2, ensure_ascii=False)
    target_cv_profile_str = json.dumps(target_cv_profile, indent=2, ensure_ascii=False)
    company_str = json.dumps(company or {}, indent=2, ensure_ascii=False)
    contact_str = json.dumps(reliable_contact or {}, indent=2, ensure_ascii=False)

    rules_str = (
        "1. Use ONLY information from the Candidate JSON / Target CV Profile / Evidence Matrix.\n"
        "2. Never invent or assume missing information (skills, employers, clients, locations, "
        "dates, numbers, certifications, achievements).\n"
        "3. Evidence rule: a job keyword is PROVABLE only when it appears in the Evidence Matrix "
        "with level >= 2 (\"\u2605\u2605\u2606\u2606\u2606\" or better) OR inside a real experience bullet, "
        "achievement, certification or language of the profile.\n"
        "4. ATS alignment: surface every PROVABLE required/preferred job keyword VERBATIM in the "
        "correct cv.skills category AND naturally inside the professional summary or the experience "
        "bullet that proves it.\n"
        "5. Never claim a job keyword that is NOT provable - add it to gaps_not_claimed instead.\n"
        "6. Rewrite experience bullets to explicitly name the truthful context facts the job asks for "
        "(industry, geography / DACH links, client nationality, language of work, scale, "
        "senior stakeholders).\n"
        "7. Never write negatives into the CV text (\"no experience in X\", \"missing\", \"weak\") - "
        "gaps belong ONLY in the optimization report.\n"
        "8. Keep dates, employers, titles, certifications and education EXACTLY as in the profile.\n"
        "9. Match the job's language requirements truthfully.\n"
        "10. Adapt the CV and Cover Letter to the specific Job and Company."
    )
    return _PROMPT_TEMPLATE.format(
        rules_str=rules_str,
        generate_cv=generate_cv,
        generate_cover_letter=generate_cover_letter,
        generate_recruiter_email=bool(reliable_contact) and generate_recruiter_email,
        candidate_str=candidate_str,
        job_str=job_str,
        ats_analysis_str=ats_analysis_str,
        gap_analysis_str=gap_analysis_str,
        evidence_str=evidence_str,
        target_cv_profile_str=target_cv_profile_str,
        company_str=company_str,
        contact_str=contact_str,
    )


_PROMPT_TEMPLATE = """
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

1. TAILORED CV  (your PRIMARY deliverable - ATS keyword alignment strategy)
   Apply this in order:
   a. Collect every required_skills / preferred_skills keyword from INPUT 2
      (Job JSON) plus the responsibilities and keywords lists.
   b. For EACH keyword, check INPUT 5 (Evidence Matrix) and INPUT 6 (Target CV
      Profile). The keyword is PROVABLE when its stars are >= 2 or when the
      keyword appears inside any real experience bullet, achievement,
      certification or language of the profile.
   c. If PROVABLE: put the keyword VERBATIM in the correct cv.skills category
      (technical / methodologies / tools) AND weave it naturally into the
      professional summary OR the experience bullet that actually proves it.
   d. If NOT provable: never list it as a skill and never write it in the CV.
      Add it to optimization_report.gaps_not_claimed.
   e. Rewrite experience bullets so each one leads with a concrete achievement
      and EXPLICITLY names the truthful context facts the job looks for:
      industry, geography / DACH-related links, client nationality, language of
      work, scale, senior stakeholders, budget, team size.
      EXAMPLE: the profile proves "customized ERP delivered for a textile firm".
      If the real stored facts include "Tunisian company, German owner, final
      client the German Federal Ministry of Defence, project delivered entirely
      in English, joint German-Tunisian operation" - write them explicitly:
      "Delivered a fully customized ERP for a Tunisian textile group
      (German-owned; final client a German federal ministry), running the whole
      engagement in English across the joint German-Tunisian organization."
      Every word you add must be a FACT already present in the profile.
   f. Re-order experiences so the most job-relevant evidence comes first.
   g. Professional summary: 2-3 sentences. Open with the role + the top 2-3 job
      keywords you can honestly claim, then your most relevant experience, then
      a fit statement for THIS job.
   h. Never write "no experience", "missing" or any negative gap sentence in the
      CV text - gaps live only in the optimization report.
   i. Keep the full_text as a clean, ready-to-use plain text version of the CV.

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
- target_keywords_used: every job keyword you surfaced in the CV, each with the
  proof you used (which skills category, which experience bullet, certification).
- strengths_emphasized: bullets rewritten / re-ordered and why.
- gaps_not_claimed: job keywords you deliberately refused to claim (not provable).
- Set evidence_based = true only if every stated fact traces back to the profile.

Now generate the documents.
"""


def generate_application_documents(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    company: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    api_key: str,
    *,
    generate_cv: bool = True,
    generate_cover_letter: bool = True,
    generate_recruiter_email: bool = True,
) -> Dict[str, Any]:
    """Main entry point of the Document Engine (V2 Step 10 output shape)."""
    parsed_job = job.get("job_json") or {}

    reliable_contact = None
    if generate_recruiter_email:
        reliable_contact = find_reliable_contact(contacts)

    prompt = _build_generation_prompt(
        candidate=candidate,
        job=job,
        parsed_job=parsed_job,
        company=company,
        reliable_contact=reliable_contact,
        generate_cv=generate_cv,
        generate_cover_letter=generate_cover_letter,
        generate_recruiter_email=generate_recruiter_email,
    )

    raw = _call_gemini(prompt, api_key=api_key, json_mode=True)
    if not raw:
        raise GatewayError("Gemini call failed - no response text.")

    try:
        cleaned = _clean_json_response(raw)
        data = json.loads(cleaned)
    except Exception as exc:  # noqa: BLE001 - parity with V2 parse guard
        raise GatewayError(f"Failed to parse Gemini response: {exc}") from exc

    # Safety: force recruiter_email.required = false if no reliable contact (Step 9)
    if not reliable_contact:
        data["recruiter_email"] = {
            "required": False,
            "to": "",
            "subject": "",
            "body": "",
            "message": "No reliable individual recruiter email was identified. Recruiter email was not generated.",
        }

    data["recruiter_contact"] = reliable_contact or {}
    return data

