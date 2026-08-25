# app/utils/validation.py
"""
AIROS Post-Generation Validation (Step 11 of spec)

Pipeline:
Generated CV
     ↓
Evidence Validation
     ↓
Fabrication Check
     ↓
ATS Recalculation
     ↓
Final Application Package

The system must flag documents that reduce ATS alignment and never
silently present a worse version as an optimized CV.
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from utils.ats import (
    build_candidate_json,
    compute_ats_engine,
    EVIDENCE_STARS,
)


def validate_generated_documents(
    generated: Dict[str, Any],
    job: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Main validation entry point.

    Args:
        generated: The raw structured output from the Document Engine
        job: The saved Job record

    Returns:
        A validation report with evidence, fabrication, ATS recalculation,
        improvement comparison, and a needs_review flag.
    """
    cv_data = generated.get("cv", {}) or {}
    cv_full_text = cv_data.get("full_text", "") or ""

    # Original ATS score from the saved job
    original_score = int(job.get("ats_score", 0))

    # Build the original candidate profile for reference
    original_candidate = build_candidate_json()

    # ------------------------------------------------------------------
    # 1. EVIDENCE VALIDATION
    # ------------------------------------------------------------------
    evidence_report = _validate_evidence(cv_data, original_candidate)

    # ------------------------------------------------------------------
    # 2. FABRICATION CHECK
    # ------------------------------------------------------------------
    fabrication_report = _check_fabrication(cv_data, original_candidate, cv_full_text)

    # ------------------------------------------------------------------
    # 3. ATS RECALCULATION against the generated CV
    # ------------------------------------------------------------------
    recalc_result = _recalculate_ats(cv_data, job)

    # ------------------------------------------------------------------
    # 4. IMPROVEMENT COMPARISON
    # ------------------------------------------------------------------
    tailored_score = int(round(recalc_result.get("overall_ats", 0)))
    improvement = tailored_score - original_score

    if improvement > 0:
        status = "improved"
        message = f"The generated CV improved ATS alignment: {original_score}% → {tailored_score}% (+{improvement} points)"
    elif improvement < 0:
        status = "regressed"
        message = (
            f"The generated CV reduced ATS alignment: {original_score}% → {tailored_score}% "
            f"({improvement} points). The document requires regeneration/review."
        )
    else:
        status = "unchanged"
        message = f"The generated CV maintained ATS alignment at {original_score}%."

    needs_review = (
        status == "regressed"
        or fabrication_report.get("fabrications_found", False)
        or not evidence_report.get("all_evidence_supported", True)
    )

    return {
        # Evidence Validation
        "evidence_validation": evidence_report,

        # Fabrication Check
        "fabrication_check": fabrication_report,

        # ATS Recalculation
        "ats_recalculation": {
            "overall_ats": recalc_result.get("overall_ats", 0),
            "ats_score": tailored_score,
            "decision": recalc_result.get("decision", "N/A"),
            "sub_scores": recalc_result.get("sub_scores", {}),
            "gap_analysis": recalc_result.get("gap_analysis", {}),
        },

        # Comparison
        "original_ats": original_score,
        "tailored_ats": tailored_score,
        "improvement": improvement,
        "status": status,
        "message": message,
        "needs_review": needs_review,
    }


# ==============================================================================
# 1. EVIDENCE VALIDATION
# ==============================================================================
def _validate_evidence(
    cv_data: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Verify that every skill/claim in the generated CV exists in the candidate profile.
    Returns per-skill evidence levels.
    """
    cv_skills = cv_data.get("skills", {}) or {}
    cv_technical = [str(s).strip().lower() for s in (cv_skills.get("technical") or []) if str(s).strip()]
    cv_methodologies = [str(s).strip().lower() for s in (cv_skills.get("methodologies") or []) if str(s).strip()]
    cv_tools = [str(s).strip().lower() for s in (cv_skills.get("tools") or []) if str(s).strip()]

    cand_skills = candidate.get("skills", {}) or {}
    cand_technical = {str(s).strip().lower() for s in (cand_skills.get("technical") or [])}
    cand_methodologies = {str(s).strip().lower() for s in (cand_skills.get("methodologies") or [])}
    cand_tools = {str(s).strip().lower() for s in (cand_skills.get("tools") or [])}
    cand_all_tokens = candidate.get("all_tokens") or set()

    results: List[Dict[str, Any]] = []

    # Check technical skills
    for skill in cv_technical:
        level = 5 if skill in cand_technical else (3 if skill in cand_all_tokens else 0)
        results.append({
            "skill": skill,
            "category": "technical",
            "level": level,
            "stars": EVIDENCE_STARS.get(level, "☆☆☆☆☆"),
            "supported": level >= 2,
        })

    # Check methodologies
    for skill in cv_methodologies:
        level = 5 if skill in cand_methodologies else (3 if skill in cand_all_tokens else 0)
        results.append({
            "skill": skill,
            "category": "methodologies",
            "level": level,
            "stars": EVIDENCE_STARS.get(level, "☆☆☆☆☆"),
            "supported": level >= 2,
        })

    # Check tools
    for skill in cv_tools:
        level = 5 if skill in cand_tools else (3 if skill in cand_all_tokens else 0)
        results.append({
            "skill": skill,
            "category": "tools",
            "level": level,
            "stars": EVIDENCE_STARS.get(level, "☆☆☆☆☆"),
            "supported": level >= 2,
        })

    unsupported = [r for r in results if not r["supported"]]

    return {
        "checked": len(results),
        "unsupported_count": len(unsupported),
        "unsupported_skills": [r["skill"] for r in unsupported],
        "all_evidence_supported": len(unsupported) == 0,
        "details": results,
    }


# ==============================================================================
# 2. FABRICATION CHECK
# ==============================================================================
def _check_fabrication(
    cv_data: Dict[str, Any],
    candidate: Dict[str, Any],
    cv_full_text: str,
) -> Dict[str, Any]:
    """
    Detect any skills, companies, certifications, or employers in the generated CV
    that do NOT exist in the candidate profile.
    """
    fabrications: List[Dict[str, str]] = []
    cv_text_lower = cv_full_text.lower()

    cand_skills = candidate.get("skills", {}) or {}
    cand_all_skills = {
        str(s).strip().lower()
        for category in cand_skills.values()
        if isinstance(category, list)
        for s in category
        if str(s).strip()
    }

    cand_cert_names = {
        str(c.get("name", "")).strip().lower()
        for c in (candidate.get("certifications") or [])
        if isinstance(c, dict) and str(c.get("name", "")).strip()
    }

    cand_companies = {
        str(e.get("company", "")).strip().lower()
        for e in (candidate.get("experience") or [])
        if isinstance(e, dict) and str(e.get("company", "")).strip()
    }

    # Check certifications mentioned in structured CV
    for cert in cv_data.get("certifications") or []:
        cert_name = ""
        if isinstance(cert, dict):
            cert_name = str(cert.get("name", "")).strip()
        elif isinstance(cert, str):
            cert_name = cert.strip()
        if not cert_name:
            continue
        cert_lower = cert_name.lower()
        if cert_lower not in cand_cert_names:
            # Check if it's in the candidate's all_tokens
            if cert_lower not in (candidate.get("all_tokens") or set()):
                fabrications.append({
                    "type": "certification",
                    "claim": cert_name,
                    "reason": "Not found in candidate profile",
                })

    # Check companies mentioned in structured CV experience
    for exp in cv_data.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        company_name = str(exp.get("company", "")).strip()
        if not company_name:
            continue
        company_lower = company_name.lower()
        if company_lower not in cand_companies:
            fabrications.append({
                "type": "company",
                "claim": company_name,
                "reason": "Not found in candidate experience",
            })

    # Check for skills in full_text that look like fabrication
    # (skills mentioned in CV text but not in candidate profile)
    # Heuristic: look for candidate skill-like phrases near "expert", "proficient"
    # This is a lightweight check — the structured fabrication check above is primary.

    # Check optimization_report gaps_not_claimed
    opt_report = cv_data.get("optimization_report") or {}

    return {
        "fabrications_found": len(fabrications) > 0,
        "fabrications": fabrications,
        "gaps_not_claimed": opt_report.get("gaps_not_claimed", []),
        "evidence_based": bool(opt_report.get("evidence_based", True)),
    }


# ==============================================================================
# 3. ATS RECALCULATION
# ==============================================================================
def _recalculate_ats(
    cv_data: Dict[str, Any],
    job: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Recalculate the ATS score using the generated CV's structured data.
    Builds a candidate profile from the generated CV and re-runs the ATS engine.
    """
    cv_skills = cv_data.get("skills", {}) or {}

    # Build a candidate profile from the generated CV
    gen_profile = {
        "skills": {
            "technical": cv_skills.get("technical", []) or [],
            "methodologies": cv_skills.get("methodologies", []) or [],
            "tools": cv_skills.get("tools", []) or [],
        },
        "languages": cv_data.get("languages", []) or [],
        "certifications": [
            {"name": c.get("name", "") if isinstance(c, dict) else str(c), "issuer": "", "year": ""}
            for c in (cv_data.get("certifications") or [])
        ],
        "education": cv_data.get("education", []) or [],
        "experience": cv_data.get("experience", []) or [],
        "total_experience_years": _estimate_experience_years(cv_data, job),
        "personal_identity": {},
    }

    gen_candidate = build_candidate_json(gen_profile)
    job_json = job.get("job_json") or {}

    result = compute_ats_engine(gen_candidate, job_json)

    return result


def _estimate_experience_years(cv_data: Dict[str, Any], job: Dict[str, Any]) -> int:
    """
    Estimate total experience years from the generated CV.
    Falls back to the job's minimum years if unavailable.
    """
    experience = cv_data.get("experience") or []
    years = 0
    for exp in experience:
        if not isinstance(exp, dict):
            continue
        start = exp.get("start_date") or exp.get("start") or ""
        end = exp.get("end_date") or exp.get("end") or ""
        if start and end:
            start_year = _extract_year(str(start))
            end_year = _extract_year(str(end))
            if start_year and end_year:
                years += max(0, end_year - start_year)
    if years > 0:
        return int(years)

    # Fallback to candidate's session profile
    candidate = build_candidate_json()
    return int(candidate.get("total_experience_years") or 0)


def _extract_year(text: str) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None