"""AIROS Post-Generation Validation (CHG-018) - port of V2
``app/utils/validation.py`` (Step 11 of the V2 spec).

Pipeline:
    Generated CV
        -> Evidence Validation
        -> Fabrication Check
        -> ATS Recalculation (deterministic engine, NO new AI call)
        -> Final Application Package

The system must flag documents that reduce ATS alignment and never silently
present a worse version as an optimized CV.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from ai.ats import EVIDENCE_STARS, build_candidate_json, compute_ats_engine

# -----------------------------------------------------------------------------
# Marginal-gain honesty (manual-test feedback, Sep 2026): when the tailored CV
# cannot move the deterministic ATS score by at least this many percentage
# points, AIROS says so explicitly and leaves the choice to the user instead of
# presenting a trivial "+1 point" as an optimization win.
# -----------------------------------------------------------------------------
MARGINAL_GAIN_THRESHOLD = 2.0


def _cv_text_tokens(text: str) -> Set[str]:
    """Word-level tokens of the generated CV text (summary + full_text).

    Mirrors the token pool build_candidate_json() derives from experience
    descriptions: ``[A-Za-z][A-Za-z0-9\\+\\#\\.]{2,}`` lower-cased. The
    post-generation ATS re-scoring must credit a keyword printed ANYWHERE in the
    final document exactly the way a real ATS parser would.
    """
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9\+\#\.]{2,}", text or "")}


def _validate_evidence(cv_data: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Verify every skill/claim in the generated CV exists in the profile."""
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

    def _check(skill: str, category: str, exact: set) -> None:
        level = 5 if skill in exact else (3 if skill in cand_all_tokens else 0)
        results.append({
            "skill": skill,
            "category": category,
            "level": level,
            "stars": EVIDENCE_STARS.get(level, "☆☆☆☆☆"),
            "supported": level >= 2,
        })

    for skill in cv_technical:
        _check(skill, "technical", cand_technical)
    for skill in cv_methodologies:
        _check(skill, "methodologies", cand_methodologies)
    for skill in cv_tools:
        _check(skill, "tools", cand_tools)

    unsupported = [r for r in results if not r["supported"]]
    return {
        "checked": len(results),
        "unsupported_count": len(unsupported),
        "unsupported_skills": [r["skill"] for r in unsupported],
        "all_evidence_supported": len(unsupported) == 0,
        "details": results,
    }


def _check_fabrication(
    cv_data: Dict[str, Any],
    candidate: Dict[str, Any],
    cv_full_text: str,
) -> Dict[str, Any]:
    """Detect skills / certifications / companies in the CV NOT in the profile."""
    fabrications: List[Dict[str, str]] = []

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

    # Certifications mentioned in the structured CV
    for cert in cv_data.get("certifications") or []:
        cert_name = ""
        if isinstance(cert, dict):
            cert_name = str(cert.get("name", "")).strip()
        elif isinstance(cert, str):
            cert_name = cert.strip()
        if not cert_name:
            continue
        cert_lower = cert_name.lower()
        if cert_lower not in cand_cert_names and cert_lower not in (candidate.get("all_tokens") or set()):
            fabrications.append({
                "type": "certification",
                "claim": cert_name,
                "reason": "Not found in candidate profile",
            })

    # Companies mentioned in the structured CV experience
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

    # Skills claimed in the CV but absent from the candidate skill pool
    cv_skills = cv_data.get("skills", {}) or {}
    for category in ("technical", "methodologies", "tools"):
        for skill in (cv_skills.get(category) or []):
            skill_lower = str(skill).strip().lower()
            if skill_lower and skill_lower not in cand_all_skills and skill_lower not in (
                candidate.get("all_tokens") or set()
            ):
                fabrications.append({
                    "type": "skill",
                    "claim": str(skill).strip(),
                    "reason": "Not found in candidate profile",
                })

    opt_report = cv_data.get("optimization_report") or {}
    return {
        "fabrications_found": len(fabrications) > 0,
        "fabrications": fabrications,
        "gaps_not_claimed": opt_report.get("gaps_not_claimed", []),
        "evidence_based": bool(opt_report.get("evidence_based", True)),
    }


def _estimate_experience_years(cv_data: Dict[str, Any], candidate: Dict[str, Any]) -> int:
    """Estimate total experience years from the generated CV (V2 heuristic)."""
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
    return int(candidate.get("total_experience_years") or 0)


def _extract_year(text: str) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None


def _recalculate_ats(cv_data: Dict[str, Any], job: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run the deterministic ATS engine against the generated CV's data.

    Objective re-scoring (manual-test feedback, Sep 2026): the recomputed score
    reflects what the FINAL document actually says, not what the profile said:

    - every structured category the document lists (technical / methodologies /
      tools) is fed into the engine - previously ``tools`` was silently dropped,
      which systematically under-scored tailored CVs;
    - the words of the CV summary and full_text join the candidate's token pool,
      so a required keyword printed anywhere in the document is credited exactly
      as a real ATS parser would credit it (fabrications are still caught by the
      evidence/fabrication guards, so the score can never be gamed by inventing
      keywords - unsupported ones raise ``needs_review``).
    """
    cv_skills = cv_data.get("skills", {}) or {}
    gen_profile = {
        "skills": {
            "TECHNICAL": cv_skills.get("technical", []) or [],
            "MANAGEMENT": cv_skills.get("methodologies", []) or [],
            "TOOLS": cv_skills.get("tools", []) or [],
        },
        "languages": cv_data.get("languages", []) or [],
        "certifications": [
            {"name": c.get("name", "") if isinstance(c, dict) else str(c), "issuer": "", "year": ""}
            for c in (cv_data.get("certifications") or [])
        ],
        "education": cv_data.get("education", []) or [],
        "experience": cv_data.get("experience", []) or [],
    }
    gen_candidate = build_candidate_json(gen_profile)
    gen_candidate["total_experience_years"] = _estimate_experience_years(cv_data, candidate)

    cv_text = " ".join(
        [
            str(cv_data.get("summary") or ""),
            str(cv_data.get("full_text") or ""),
        ]
    )
    extra_tokens = _cv_text_tokens(cv_text)
    if extra_tokens:
        tokens = set(gen_candidate.get("all_tokens") or [])
        tokens.update(extra_tokens)
        gen_candidate["all_tokens"] = sorted(tokens)

    job_json = job.get("job_json") or {}
    return compute_ats_engine(gen_candidate, job_json)


def _required_job_keywords(job_json: Dict[str, Any]) -> Set[str]:
    """Normalized set of the keywords the job REQUIRES (score-affecting only:
    required skills + certifications). Every one of them checks the generated
    CV's free text for unsupported claims."""
    required: Set[str] = set()
    for cat in ("technical", "methodologies", "tools"):
        for item in (job_json.get("required_skills", {}).get(cat) or []):
            text = str(item or "").strip().lower()
            if text:
                required.add(text)
    for cert in (job_json.get("certifications") or []):
        name = cert.get("name") if isinstance(cert, dict) else cert
        text = str(name or "").strip().lower()
        if text:
            required.add(text)
    return required


def _provable_keywords(candidate: Dict[str, Any]) -> Set[str]:
    """Everything the caller's profile can truthfully prove: every structured
    skill (all categories) + every token in the profile text pool."""
    provable: Set[str] = set()
    skills = candidate.get("skills") or {}
    for category in skills.values():
        if isinstance(category, list):
            provable.update(str(s).strip().lower() for s in category if str(s).strip())
    provable.update(str(t).lower() for t in (candidate.get("all_tokens") or []))
    return provable


def validate_generated_documents(
    generated: Dict[str, Any],
    job: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """Main validation entry point (V2 parity, candidate passed by the caller).

    Args:
        generated: raw structured output of the Document Engine
        job: the saved Job record (original ATS score + parsed JD)
        candidate: the candidate built from the caller's OWN profile
            (``ai.ats.build_candidate_json``)

    Returns the full validation report incl. improvement comparison and a
    needs_review flag.
    """
    cv_data = generated.get("cv", {}) or {}
    cv_full_text = cv_data.get("full_text", "") or ""
    original_score = int(job.get("ats_score", 0) or 0)

    evidence_report = _validate_evidence(cv_data, candidate)
    fabrication_report = _check_fabrication(cv_data, candidate, cv_full_text)

    # Text-level truthfulness guard: the deterministic recompute credits
    # keywords PRINTED in the document (summary + full_text) exactly as a real
    # ATS would. A job-required keyword that appears in the generated text
    # without being provable from the profile would therefore inflate the score
    # while being unsupported - flag it as a fabrication so the result can
    # never be silently presented as a valid win (manual-test feedback:
    # "without inventing missed skills").
    job_json = job.get("job_json") or {}
    required_keywords = _required_job_keywords(job_json)
    provable = _provable_keywords(candidate)
    text_tokens = _cv_text_tokens(str(cv_data.get("summary") or "") + " " + cv_full_text)
    text_fabrications = sorted(
        k for k in required_keywords if k in text_tokens and k not in provable
    )
    if text_fabrications:
        fabrication_report = dict(fabrication_report)
        fabrication_report["text_fabrications"] = text_fabrications
        fabrication_report["fabrications_found"] = True

    recalc_result = _recalculate_ats(cv_data, job, candidate)

    tailored_score = int(round(recalc_result.get("overall_ats", 0) or 0))
    improvement = tailored_score - original_score
    delta = float(improvement)

    if delta >= MARGINAL_GAIN_THRESHOLD:
        status = "improved"
        message = (
            f"The tailored CV improved ATS alignment: {original_score}% -> {tailored_score}% "
            f"(+{improvement} points)."
        )
    elif delta < 0:
        status = "regressed"
        message = (
            f"The generated CV reduced ATS alignment: {original_score}% -> {tailored_score}% "
            f"({improvement} points). The document requires regeneration/review."
        )
    else:
        # Honest marginal-gain verdict (manual-test feedback, Sep 2026): a gain
        # smaller than 2 points is not a real optimization win - AIROS says so
        # and leaves the choice between the original and the tailored CV to the
        # user instead of overselling the result.
        status = "marginal"
        message = (
            f"AIROS could not drive a meaningful ATS gain: the tailored CV scores "
            f"{tailored_score}% vs {original_score}% for the original ({improvement:+d} points, "
            f"below the {MARGINAL_GAIN_THRESHOLD:g}-point threshold). For this profile and this "
            f"job description nothing more could be improved while staying truthful. You are free "
            f"to choose between your original CV and this tailored version."
        )

    needs_review = (
        status == "regressed"
        or fabrication_report.get("fabrications_found", False)
        or not evidence_report.get("all_evidence_supported", True)
    )

    return {
        "evidence_validation": evidence_report,
        "fabrication_check": fabrication_report,
        "ats_recalculation": {
            "overall_ats": recalc_result.get("overall_ats", 0),
            "ats_score": tailored_score,
            "decision": recalc_result.get("decision", "N/A"),
            "sub_scores": recalc_result.get("sub_scores", {}),
            "gap_analysis": recalc_result.get("gap_analysis", {}),
        },
        "original_ats": original_score,
        "tailored_ats": tailored_score,
        "improvement": improvement,
        "marginal_gain_threshold": MARGINAL_GAIN_THRESHOLD,
        "status": status,
        "message": message,
        "needs_review": needs_review,
        # Absolute-objectivity note (requirement from the manual test): the
        # tailored score is a deterministic re-run of the SAME engine on the
        # generated document's own content - never an AI round-trip.
        "objective": True,
        "objective_note": (
            "The tailored score is recomputed deterministically from the generated "
            "document's own content (skills, experience, certifications, summary and "
            "full text) with the same engine and weights as the original analysis - "
            "no AI round-trip, so the comparison cannot be influenced by the model."
        ),
    }

