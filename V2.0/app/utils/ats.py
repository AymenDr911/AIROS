"""
AIROS V2 — ATS Engine (Advanced)
================================
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import streamlit as st

# ==============================================================================
# 1. CORE GEMINI CONNECTOR
# ==============================================================================
MODEL_FALLBACK_CHAIN = [
    "gemini-3.7-flash",      # Latest Flash (Aug 2026)
    "gemini-3.6-flash",      # Recommended by Google (replaces 2.5)
    "gemini-3.5-flash",
]

def _call_gemini(prompt: str, json_mode: bool = False, max_retries: int = 2) -> Optional[str]:
    """Robust Gemini REST connector."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        st.error("GEMINI_API_KEY missing. Please add it to .streamlit/secrets.toml or environment variables.")
        return None

    api_key = api_key.strip().strip("'\"")
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    last_error = "No models attempted."

    for model in MODEL_FALLBACK_CHAIN:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        for attempt in range(1, max_retries + 1):
            try:
                req_data = json.dumps(payload).encode("utf-8")
                request = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=45) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    candidates = result.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                break
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="ignore")
                last_error = f"Model '{model}' → HTTP {e.code}: {error_body[:300]}"
                if e.code in (401, 403):
                    st.error(f"Gemini API Auth Error: {error_body[:400]}")
                    return None
                if e.code in (404, 400):
                    break
                if e.code in (503, 429):
                    time.sleep(1.5 * attempt)
                    continue
                break
            except Exception as e:
                last_error = f"Model '{model}' → Exception: {str(e)}"
                time.sleep(1.0)
                continue

    st.error(f"Gemini API Connection Failed. Diagnostic details:\n{last_error}")
    return None


def _get_text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _clean_json_response(raw_response: str) -> str:
    cleaned = raw_response.strip()
    json_match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    return json_match.group(1) if json_match else cleaned

# ==============================================================================
# 2. CANDIDATE JSON BUILDER
# ==============================================================================
def build_candidate_json(profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if profile is None:
        profile = {
            "personal_identity": st.session_state.get("personal_identity", {}),
            "career_stage": st.session_state.get("career_stage")
                or st.session_state.get("career_stage_suggestion", ""),
            "education": st.session_state.get("education", []),
            "experience": st.session_state.get("experience", []),
            "skills": st.session_state.get("skills", {}),
            "languages": st.session_state.get("languages", []),
            "certifications": st.session_state.get("certifications", []),
            "total_experience_years": st.session_state.get("total_experience_years"),
            "cv_extracted": st.session_state.get("cv_extracted", {}),
        }

    skills = profile.get("skills") or {}
    if not isinstance(skills, dict):
        skills = {}

    technical = [str(s).strip() for s in (skills.get("technical") or []) if str(s).strip()]
    methodologies = [str(s).strip() for s in (skills.get("methodologies") or []) if str(s).strip()]
    tools = [str(s).strip() for s in (skills.get("tools") or []) if str(s).strip()]

    languages_raw = profile.get("languages") or []
    languages: List[Dict[str, str]] = []
    if isinstance(languages_raw, list):
        for lang in languages_raw:
            if isinstance(lang, dict):
                languages.append({
                    "language": str(lang.get("language", "")).strip(),
                    "level": str(lang.get("level", "")).strip(),
                })
            else:
                languages.append({"language": str(lang).strip(), "level": ""})
    elif isinstance(languages_raw, str):
        for part in languages_raw.split(","):
            part = part.strip()
            if part:
                languages.append({"language": part, "level": ""})

    certs_raw = profile.get("certifications") or []
    certifications: List[Dict[str, str]] = []
    if isinstance(certs_raw, list):
        for c in certs_raw:
            if isinstance(c, dict):
                certifications.append({
                    "name": str(c.get("name", "")).strip(),
                    "issuer": str(c.get("issuer", "")).strip(),
                    "year": str(c.get("year", "")).strip(),
                })
            else:
                certifications.append({"name": str(c).strip(), "issuer": "", "year": ""})

    # ----------------------------------------------------------------------
    # Robust total_experience_years – DO NOT use the old crude estimate
    # ----------------------------------------------------------------------
    total_years = None

    # Priority 1: direct key
    raw = profile.get("total_experience_years")
    if isinstance(raw, (int, float)) and raw > 0:
        total_years = raw

    # Priority 2: nested inside cv_extracted (very common in your flow)
    if total_years is None:
        cv_ex = profile.get("cv_extracted") or {}
        if isinstance(cv_ex, dict):
            raw = cv_ex.get("total_experience_years")
            if isinstance(raw, (int, float)) and raw > 0:
                total_years = raw

    # Priority 3: session state
    if total_years is None:
        raw = st.session_state.get("total_experience_years")
        if isinstance(raw, (int, float)) and raw > 0:
            total_years = raw

    # Priority 4: last resort only
    if total_years is None:
        experience = profile.get("experience") or []
        if isinstance(experience, list) and len(experience) > 0:
            total_years = min(len(experience) * 2, 25)
        else:
            total_years = 0

    total_years = int(round(float(total_years)))

    personal = profile.get("personal_identity") or {}
    if not isinstance(personal, dict):
        personal = {}

    return {
        "personal_identity": personal,
        "career_stage": str(profile.get("career_stage") or profile.get("career_stage_suggestion") or ""),
        "education": profile.get("education") or [],
        "experience": profile.get("experience") or [],
        "skills": {
            "technical": technical,
            "methodologies": methodologies,
            "tools": tools,
        },
        "languages": languages,
        "certifications": certifications,
        "total_experience_years": total_years,
        "location": personal.get("location") or personal.get("country") or "",
        "nationality": personal.get("nationality") or personal.get("citizenship") or "",
        "industry_hints": _extract_industry_hints(profile),
        "all_tokens": sorted(_build_all_tokens(technical, methodologies, tools, languages, certifications, profile)),
    }
def _extract_industry_hints(profile: Dict[str, Any]) -> List[str]:
    hints: Set[str] = set()
    experience = profile.get("experience") or []
    for exp in experience:
        if isinstance(exp, dict):
            for field in ("company", "title", "description"):
                text = str(exp.get(field, "")).lower()
                for kw in (
                    "finance", "banking", "insurance", "healthcare", "pharma",
                    "telecom", "retail", "manufacturing", "automotive", "energy",
                    "oil", "gas", "consulting", "technology", "software", "saas",
                    "public sector", "government", "defence", "aerospace",
                    "logistics", "supply chain", "erp", "sap", "oracle",
                ):
                    if kw in text:
                        hints.add(kw)
    return sorted(hints)


def _build_all_tokens(
    technical: List[str],
    methodologies: List[str],
    tools: List[str],
    languages: List[Dict[str, str]],
    certifications: List[Dict[str, str]],
    profile: Dict[str, Any],
) -> Set[str]:
    tokens: Set[str] = set()
    for item in technical + methodologies + tools:
        tokens.add(item.lower().strip())
    for lang in languages:
        tokens.add(lang.get("language", "").lower().strip())
    for cert in certifications:
        tokens.add(cert.get("name", "").lower().strip())
    for exp in profile.get("experience") or []:
        if isinstance(exp, dict):
            desc = str(exp.get("description", "")) + " " + " ".join(exp.get("achievements") or [])
            for word in re.findall(r"[A-Za-z][A-Za-z0-9\+\#\.]{2,}", desc):
                tokens.add(word.lower())
    return tokens


# ==============================================================================
# 3. JOB JSON – Gemini ONE CALL only
# ==============================================================================

def parse_job_v2(job_text: str, force_refresh: bool = False) -> Dict[str, Any]:
    job_hash = _get_text_hash(job_text)
    cache_key = f"parsed_job_v2_{job_hash}"

    if not force_refresh and cache_key in st.session_state:
        cached = st.session_state[cache_key]
        if not cached.get("_api_error"):
            return cached

    prompt = f"""
You are a senior recruitment analyst specialized in precise, non-hallucinated job parsing.
Extract a structured job profile from the Job Description below.
Return ONLY valid JSON that strictly follows the schema. Never invent requirements that are not clearly present.

OUTPUT SCHEMA (strict – follow exactly):
{{
  "job_title": "",
  "company_name": "",
  "location": "",
  "country": "",
  "city": "",
  "address": "",
  "company_website": "",
  "company_linkedin": "",
  "company_phone": "",
  "industry": "",
  "seniority_level": "",
  "visa_sponsorship": {{
    "support": "Yes | No | Not mentioned",
    "evidence": "",
    "notes": ""
  }},
  "work_authorization": {{
    "requirement": "Must already have right to work | Sponsorship available | Not mentioned",
    "evidence": ""
  }},
  "required_skills": {{
    "technical": [],
    "methodologies": [],
    "tools": []
  }},
  "preferred_skills": {{
    "technical": [],
    "methodologies": [],
    "tools": []
  }},
  "experience": {{
    "min_years": 0,
    "preferred_years": 0,
    "level": ""
  }},
  "education": {{
    "min_degree": "",
    "preferred_fields": []
  }},
  "languages": [
    {{
      "language": "",
      "level": "",
      "required": true,
      "type": "spoken | programming",
      "evidence": ""
    }}
  ],
  "certifications": [],
  "responsibilities": [],
  "keywords": [],
  "location_requirements": {{
    "remote": false,
    "hybrid": false,
    "on_site": false,
    "cities_or_countries": [],
    "relocation_support": "Yes | No | Not mentioned"
  }}
}},
  "work_authorization": {{
    "requirement": "Must already have right to work | Sponsorship available | Not mentioned",
    "evidence": ""
  }},
  "required_skills": {{
    "technical": [],
    "methodologies": [],
    "tools": []
  }},
  "preferred_skills": {{
    "technical": [],
    "methodologies": [],
    "tools": []
  }},
  "experience": {{
    "min_years": 0,
    "preferred_years": 0,
    "level": ""
  }},
  "education": {{
    "min_degree": "",
    "preferred_fields": []
  }},
  "languages": [
    {{
      "language": "",
      "level": "",
      "required": true,
      "type": "spoken | programming",
      "evidence": ""
    }}
  ],
  "certifications": [],
  "responsibilities": [],
  "industry": "",
  "keywords": [],
  "location_requirements": {{
    "remote": false,
    "hybrid": false,
    "on_site": false,
    "cities_or_countries": [],
    "relocation_support": "Yes | No | Not mentioned"
  }}
}}
STRICT RULES (must follow):
0. COMPANY & LOCATION (very important)
   - company_name: Extract the real hiring company name (e.g. "Siemens AG", "BMW Group", "Google"). 
     Never put the job board (LinkedIn, Indeed, StepStone…) as company_name.
   - location: City or region where the job is based (e.g. "Munich", "Paris", "Remote - Germany").
   - country: Full country name or ISO code if clearly stated (e.g. "Germany", "France", "Remote").
   - If the information is not present, leave the field as empty string "".

1. VISA / WORK AUTHORIZATION (critical)
   - Decide "Yes", "No" or "Not mentioned" based only on explicit statements.
   - Positive signals: "visa sponsorship", "we sponsor", "Blue Card", "relocation package", "work permit support", etc.
   - Negative signals: "no visa sponsorship", "must already have the right to work", "EU citizens only", "no sponsorship", etc.
   - If both positive and negative signals exist, prefer the most restrictive one and explain in notes.
   - Never assume sponsorship just because the company is international.

2. TECHNICAL SKILLS – solid logic, zero repetition
   - Break every skill into short atomic items (e.g. "Python", "Azure DevOps", "Kubernetes", "PRINCE2").
   - required_skills = must-have / mandatory.
   - preferred_skills = nice-to-have / bonus.
   - Classification rules:
     • technical = programming languages, frameworks, libraries, cloud platforms, databases, architecture styles…
     • methodologies = Agile, Scrum, SAFe, Kanban, PRINCE2, ITIL, PMI, Lean, Six Sigma, Design Thinking…
     • tools = specific platforms, ERP, CI/CD tools, monitoring, project management tools, IDEs…
   - Deduplicate aggressively: the same skill must appear in only one place (required or preferred, and only one category).
   - If a skill is mentioned multiple times with different wordings, keep the clearest canonical form once.
   - Do not put soft skills or generic adjectives here.

3. LANGUAGES – careful identification
   - Only extract human (spoken/written) languages and programming languages that are explicitly required or preferred.
   - For each language:
     • Set "type": "spoken" or "programming".
     • Extract level only if mentioned (Native, Fluent, C1, B2, Professional, Intermediate…).
     • Set "required": true only if the JD makes it mandatory.
   - Quote the exact short evidence phrase.
   - Never invent a language requirement from generic phrases like "excellent communication skills".

4. GENERAL
   - experience.min_years = the lowest number clearly stated. preferred_years if a range is given.
   - Never invent. Empty lists / "Not mentioned" are perfectly fine and preferred over guesses.
   - Keep lists short and high-signal.

Job Description:
{job_text[:25000]}
"""

    response = _call_gemini(prompt, json_mode=True)

    default: Dict[str, Any] = {
        "job_title": "",
        "company_name": "",
        "location": "",
        "country": "",
        "seniority_level": "",
        "required_skills": {"technical": [], "methodologies": [], "tools": []},
        "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [],
        "certifications": [],
        "responsibilities": [],
        "industry": "",
        "keywords": [],
        "visa_sponsorship": {},
        "work_authorization": {},
        "location_requirements": {},
        "_api_error": True,
    }

    if not response:
        st.session_state[cache_key] = default
        return default

    try:
        cleaned = _clean_json_response(response)
        parsed = json.loads(cleaned)

        def _list(val) -> List[str]:
            if isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
            return []

        result = {
            "job_title": str(parsed.get("job_title") or "").strip(),
            "company_name": str(parsed.get("company_name") or "").strip(),
            "location": str(parsed.get("location") or "").strip(),
            "city": str(parsed.get("city") or parsed.get("location") or "").strip(),
            "country": str(parsed.get("country") or "").strip(),
            "address": str(parsed.get("address") or "").strip(),
            "company_website": str(parsed.get("company_website") or "").strip(),
            "company_linkedin": str(parsed.get("company_linkedin") or "").strip(),
            "company_phone": str(parsed.get("company_phone") or "").strip(),
            "industry": str(parsed.get("industry") or "").strip(),
            "seniority_level": str(parsed.get("seniority_level") or "").strip(),

            "required_skills": {
                "technical": _list((parsed.get("required_skills") or {}).get("technical")),
                "methodologies": _list((parsed.get("required_skills") or {}).get("methodologies")),
                "tools": _list((parsed.get("required_skills") or {}).get("tools")),
            },
            "preferred_skills": {
                "technical": _list((parsed.get("preferred_skills") or {}).get("technical")),
                "methodologies": _list((parsed.get("preferred_skills") or {}).get("methodologies")),
                "tools": _list((parsed.get("preferred_skills") or {}).get("tools")),
            },
            "experience": {
                "min_years": int((parsed.get("experience") or {}).get("min_years") or 0),
                "preferred_years": int((parsed.get("experience") or {}).get("preferred_years") or 0),
                "level": str((parsed.get("experience") or {}).get("level") or "").strip(),
            },
            "education": {
                "min_degree": str((parsed.get("education") or {}).get("min_degree") or "").strip(),
                "preferred_fields": _list((parsed.get("education") or {}).get("preferred_fields")),
            },
            "languages": [],
            "certifications": _list(parsed.get("certifications")),
            "responsibilities": _list(parsed.get("responsibilities")),
            "keywords": _list(parsed.get("keywords")),

            "visa_sponsorship": parsed.get("visa_sponsorship") or {},
            "work_authorization": parsed.get("work_authorization") or {},
            "location_requirements": parsed.get("location_requirements") or {},

            "_api_error": False,
        }

        for lang in parsed.get("languages") or []:
            if isinstance(lang, dict):
                result["languages"].append({
                    "language": str(lang.get("language") or "").strip(),
                    "level": str(lang.get("level") or "").strip(),
                    "required": bool(lang.get("required", True)),
                })
            elif isinstance(lang, str) and lang.strip():
                result["languages"].append({"language": lang.strip(), "level": "", "required": True})

        st.session_state[cache_key] = result
        return result

    except Exception:
        st.session_state[cache_key] = default
        return default


# ==============================================================================
# 4. HARD BLOCKERS
# ==============================================================================

def check_hard_blockers(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    raw_job_text: str = "",
) -> Tuple[List[str], List[str]]:
    blockers: List[str] = []
    explanations: List[str] = []
    job_lower = (raw_job_text or "").lower()

    if job.get("_api_error"):
        blockers.append("API Failure")
        explanations.append("Unable to analyse job requirements properly.")
        return blockers, explanations

    # ---------- VISA / WORK AUTHORIZATION ----------
    positive_visa = [
        "visa sponsorship", "sponsorship provided", "blue card",
        "relocation package", "relocation support", "we sponsor",
        "full visa", "visa support", "work permit support"
    ]
    negative_visa = [
        "no visa sponsorship", "sponsorship not available", "no sponsorship",
        "must already have the right to work", "must have the right to work",
        "eu citizens only", "only eu citizens", "no visa"
    ]
    has_positive = any(p in job_lower for p in positive_visa)
    has_negative = any(n in job_lower for n in negative_visa)

    if has_negative and not has_positive:
        loc = (candidate.get("location") or "").lower()
        nat = (candidate.get("nationality") or "").lower()
        if any(x in loc or x in nat for x in ("tunisia", "mena", "africa", "non-eu", "asia")):
            blockers.append("No Visa Sponsorship")
            explanations.append(
                "The job does not offer visa sponsorship. Candidate location/nationality "
                "indicates a strong barrier."
            )

    critical = {"german", "dutch", "nederlands", "swedish", "deutsch", "french", "français"}
    cand_langs = {l.get("language", "").lower() for l in candidate.get("languages") or []}
    for lang_req in job.get("languages") or []:
        lang_name = (lang_req.get("language") or "").lower()
        if lang_name in critical and lang_name not in cand_langs:
            blockers.append(f"Local Language: {lang_req.get('language', lang_name).title()}")
            explanations.append(
                f"Role requires strong {lang_req.get('language', lang_name).title()} proficiency "
                "which is not present in the candidate profile."
            )

    if any(p in job_lower for p in ("immediate", "asap", "1 month", "within 1 month", "short notice")):
        loc = (candidate.get("location") or "").lower()
        if "tunisia" in loc or "mena" in loc:
            blockers.append("Relocation / Notice Period")
            explanations.append(
                "Job requires a very fast start. Candidate location makes immediate availability unrealistic."
            )

    cand_years = int(candidate.get("total_experience_years") or 0)
    req_years = int((job.get("experience") or {}).get("min_years") or 0)
    if req_years > 0 and cand_years < req_years * 0.70:
        blockers.append("Major Experience Gap")
        explanations.append(
            f"Role requires ~{req_years}+ years. Candidate has approximately {cand_years} years."
        )

    return blockers, explanations


# ==============================================================================
# 5. EVIDENCE LEVEL SYSTEM
# ==============================================================================

EVIDENCE_STARS = {
    5: "★★★★★",
    4: "★★★★☆",
    3: "★★★☆☆",
    2: "★★☆☆☆",
    1: "★☆☆☆☆",
    0: "☆☆☆☆☆",
}


def _token_match(target: str, tokens: Set[str]) -> bool:
    t = target.lower().strip()
    if not t:
        return True
    if t in tokens:
        return True
    pattern = r"(?<!\w)" + re.escape(t) + r"(?!\w)"
    return any(re.search(pattern, tok) for tok in tokens if len(t) >= 3)


def _evidence_level(item: str, candidate: Dict[str, Any], category: str) -> int:
    item_l = item.lower().strip()
    if not item_l:
        return 5

    skills = candidate.get("skills") or {}
    technical = {s.lower() for s in skills.get("technical") or []}
    methodologies = {s.lower() for s in skills.get("methodologies") or []}
    tools = {s.lower() for s in skills.get("tools") or []}
    cert_names = {c.get("name", "").lower() for c in candidate.get("certifications") or []}
    lang_names = {l.get("language", "").lower() for l in candidate.get("languages") or []}

    # --- Special handling for certifications (fuzzy) ---
    if category == "certifications":
        # exact
        if item_l in cert_names:
            return 5
        # common short forms
        short_map = {
            "pmp": ["pmp", "project management professional", "project manager professional"],
            "sfc": ["sfc", "scrum fundamentals", "scrum fundamentals certified"],
            "six sigma": ["six sigma", "six sigma yellow belt", "yellow belt"],
            "okr": ["okr", "okr fundamentals"],
            "prince2": ["prince2"],
            "itil": ["itil"],
        }
        for key, variants in short_map.items():
            if key in item_l or any(v in item_l for v in variants):
                if any(any(v in c for v in variants) or key in c for c in cert_names):
                    return 5
        # partial match
        for c in cert_names:
            if item_l in c or c in item_l:
                return 4
        return 0

    # --- normal categories ---
    if category == "technical" and item_l in technical:
        return 5
    if category == "methodologies" and item_l in methodologies:
        return 5
    if category == "tools" and item_l in tools:
        return 5
    if category == "languages" and item_l in lang_names:
        return 5

    if item_l in technical | methodologies | tools | cert_names | lang_names:
        return 4

    all_tokens = candidate.get("all_tokens") or set()
    if item_l in all_tokens:
        return 3
    for tok in all_tokens:
        if len(item_l) >= 4 and (item_l in tok or tok in item_l):
            return 2
    return 0


# ==============================================================================
# 6. DETERMINISTIC ATS ENGINE
# ==============================================================================

DEFAULT_WEIGHTS = {
    "technical_skills": 0.30,
    "experience": 0.25,
    "methodologies": 0.10,
    "tools": 0.10,
    "languages": 0.10,
    "education": 0.05,
    "certifications": 0.05,
    "industry": 0.05,
}


def _score_list_match(
    required: List[str],
    candidate: Dict[str, Any],
    category: str,
) -> Tuple[float, List[Dict[str, Any]], List[str]]:
    if not required:
        return 100.0, [], []

    evidence: List[Dict[str, Any]] = []
    missing: List[str] = []
    matched_count = 0

    for item in required:
        level = _evidence_level(item, candidate, category)
        if level >= 2:
            matched_count += 1
            evidence.append({
                "item": item,
                "category": category,
                "level": level,
                "stars": EVIDENCE_STARS[level],
                "source": "explicit" if level >= 4 else "professional_use",
            })
        else:
            missing.append(item)
            evidence.append({
                "item": item,
                "category": category,
                "level": level,
                "stars": EVIDENCE_STARS[level],
                "source": "missing" if level == 0 else "weak",
            })

    score = round((matched_count / len(required)) * 100.0, 1)
    return score, evidence, missing


def _score_experience(candidate: Dict[str, Any], job: Dict[str, Any]) -> float:
    cand_years = int(candidate.get("total_experience_years") or 0)
    min_years = int((job.get("experience") or {}).get("min_years") or 0)
    pref_years = int((job.get("experience") or {}).get("preferred_years") or 0)

    if min_years == 0 and pref_years == 0:
        return 100.0

    target = pref_years if pref_years > 0 else min_years

    if cand_years >= target:
        return 100.0
    if cand_years >= min_years:
        if pref_years > min_years:
            return round(70 + 30 * (cand_years - min_years) / (pref_years - min_years), 1)
        return 85.0
    return round(max(0.0, (cand_years / max(min_years, 1)) * 70.0), 1)


def _score_education(candidate: Dict[str, Any], job: Dict[str, Any]) -> float:
    edu_req = job.get("education") or {}
    min_degree = (edu_req.get("min_degree") or "").lower()
    preferred_fields = [f.lower() for f in (edu_req.get("preferred_fields") or [])]

    if not min_degree and not preferred_fields:
        return 100.0

    cand_edu = candidate.get("education") or []
    if not cand_edu:
        return 40.0

    degree_score = 60.0
    field_score = 40.0

    degree_map = {
        "phd": 5, "doctorate": 5, "master": 4, "msc": 4, "mba": 4,
        "bachelor": 3, "bsc": 3, "ba": 3, "licence": 3,
        "associate": 2, "diploma": 2, "high school": 1,
    }

    required_level = 0
    for k, v in degree_map.items():
        if k in min_degree:
            required_level = v
            break

    best_cand_level = 0
    best_field_match = False

    for edu in cand_edu:
        if not isinstance(edu, dict):
            continue
        deg = (edu.get("degree") or "").lower()
        field = (edu.get("field") or "").lower()
        for k, v in degree_map.items():
            if k in deg:
                best_cand_level = max(best_cand_level, v)
        if preferred_fields and any(pf in field for pf in preferred_fields):
            best_field_match = True

    if required_level == 0 or best_cand_level >= required_level:
        degree_score = 100.0
    elif best_cand_level > 0:
        degree_score = round((best_cand_level / required_level) * 80.0, 1)
    else:
        degree_score = 30.0

    if preferred_fields:
        field_score = 100.0 if best_field_match else 40.0
    else:
        field_score = 100.0

    return round(degree_score * 0.7 + field_score * 0.3, 1)


def _score_languages(candidate: Dict[str, Any], job: Dict[str, Any]) -> Tuple[float, List[Dict], List[str]]:
    req_langs = job.get("languages") or []
    if not req_langs:
        return 100.0, [], []

    cand_map = {
        (l.get("language") or "").lower(): (l.get("level") or "").lower()
        for l in candidate.get("languages") or []
    }

    evidence: List[Dict] = []
    missing: List[str] = []
    matched = 0

    level_order = {
        "a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6,
        "native": 7, "fluent": 6, "professional": 5
    }

    for req in req_langs:
        lang = (req.get("language") or "").strip()
        req_level = (req.get("level") or "").lower()
        lang_l = lang.lower()

        if lang_l in cand_map:
            cand_level = cand_map[lang_l]
            req_val = level_order.get(req_level, 0)
            cand_val = level_order.get(cand_level, 4)

            if req_val == 0 or cand_val >= req_val:
                matched += 1
                evidence.append({
                    "item": f"{lang} ({cand_level or 'present'})",
                    "category": "languages",
                    "level": 5,
                    "stars": EVIDENCE_STARS[5],
                    "source": "explicit",
                })
            else:
                missing.append(f"{lang} {req_level}".strip())
                evidence.append({
                    "item": f"{lang} (have {cand_level}, need {req_level})",
                    "category": "languages",
                    "level": 2,
                    "stars": EVIDENCE_STARS[2],
                    "source": "level_gap",
                })
        else:
            missing.append(f"{lang} {req_level}".strip())
            evidence.append({
                "item": lang,
                "category": "languages",
                "level": 0,
                "stars": EVIDENCE_STARS[0],
                "source": "missing",
            })

    score = round((matched / len(req_langs)) * 100.0, 1)
    return score, evidence, missing


def _score_industry(candidate: Dict[str, Any], job: Dict[str, Any]) -> float:
    job_industry = (job.get("industry") or "").lower()
    if not job_industry:
        return 100.0

    hints = [h.lower() for h in candidate.get("industry_hints") or []]
    if any(job_industry in h or h in job_industry for h in hints):
        return 100.0

    all_tokens = candidate.get("all_tokens") or set()
    if any(job_industry in t for t in all_tokens):
        return 70.0

    return 40.0


def compute_ats_engine(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    weights = weights or DEFAULT_WEIGHTS

    all_evidence: List[Dict[str, Any]] = []
    missing: List[str] = []
    strengths: List[str] = []

    tech_score, tech_ev, tech_miss = _score_list_match(
        job.get("required_skills", {}).get("technical") or [],
        candidate,
        "technical",
    )
    all_evidence.extend(tech_ev)
    missing.extend(tech_miss)

    meth_score, meth_ev, meth_miss = _score_list_match(
        job.get("required_skills", {}).get("methodologies") or [],
        candidate,
        "methodologies",
    )
    all_evidence.extend(meth_ev)
    missing.extend(meth_miss)

    tools_score, tools_ev, tools_miss = _score_list_match(
        job.get("required_skills", {}).get("tools") or [],
        candidate,
        "tools",
    )
    all_evidence.extend(tools_ev)
    missing.extend(tools_miss)

    cert_score, cert_ev, cert_miss = _score_list_match(
        job.get("certifications") or [],
        candidate,
        "certifications",
    )
    all_evidence.extend(cert_ev)
    missing.extend(cert_miss)

    lang_score, lang_ev, lang_miss = _score_languages(candidate, job)
    all_evidence.extend(lang_ev)
    missing.extend(lang_miss)

    exp_score = _score_experience(candidate, job)
    edu_score = _score_education(candidate, job)
    ind_score = _score_industry(candidate, job)

    for cat in ("technical", "methodologies", "tools"):
        for item in job.get("preferred_skills", {}).get(cat) or []:
            level = _evidence_level(item, candidate, cat)
            if level >= 3:
                strengths.append(item)

    for ev in all_evidence:
        if ev["level"] >= 4:
            strengths.append(ev["item"])

    # ------------------------------------------------------------------
    # Coherence filter – never allow the same or near-same item on both sides
    # ------------------------------------------------------------------
    def _normalize(text: str) -> str:
        t = text.lower().strip()
        # remove common noise words that create false gaps
        for noise in ["credentials", "certificate", "certification", "experience", "knowledge", "skills", "skill"]:
            t = t.replace(noise, "").strip()
        return t

    strengths_norm = {_normalize(s) for s in strengths}
    missing = [m for m in missing if _normalize(m) not in strengths_norm]

    strengths = sorted(set(strengths))
    missing = sorted(set(missing))

    sub_scores = {
        "technical_skills": tech_score,
        "experience": exp_score,
        "methodologies": meth_score,
        "tools": tools_score,
        "languages": lang_score,
        "education": edu_score,
        "certifications": cert_score,
        "industry": ind_score,
    }
    overall = 0.0
    for key, w in weights.items():
        overall += sub_scores.get(key, 0.0) * w
    overall = round(overall, 1)

    if overall >= 90:
        decision = "Excellent Match"
    elif overall >= 80:
        decision = "Strong Match"
    elif overall >= 70:
        decision = "Good Match"
    elif overall >= 60:
        decision = "Moderate Match"
    else:
        decision = "Weak Match"

    return {
        "overall_ats": overall,
        "decision": decision,
        "sub_scores": sub_scores,
        "weights": weights,
        "gap_analysis": {
            "missing": missing,
            "strengths": strengths,
        },
        "evidence": all_evidence,
        "hard_blockers": [],
        "blocker_explanations": [],
        "job_json": job,
        "candidate_json": {
            "total_experience_years": candidate.get("total_experience_years"),
            "skills_count": {
                "technical": len(candidate.get("skills", {}).get("technical") or []),
                "methodologies": len(candidate.get("skills", {}).get("methodologies") or []),
                "tools": len(candidate.get("skills", {}).get("tools") or []),
            },
        },
    }


# ==============================================================================
# 7. PUBLIC API – main entry point
# ==============================================================================

def calculate_ats_gap(
    cv_input: Union[str, Dict[str, Any]],
    job_text: str,
    force_job_refresh: bool = False,
) -> Dict[str, Any]:
    if isinstance(cv_input, dict) and "skills" in cv_input:
        if "total_experience_years" in cv_input or "all_tokens" in cv_input:
            candidate = cv_input
        else:
            candidate = build_candidate_json({
                "skills": {
                    "technical": cv_input.get("technical_skills") or cv_input.get("mandatory_skills") or [],
                    "methodologies": [],
                    "tools": cv_input.get("technical_skills") or [],
                },
                "languages": [{"language": l, "level": ""} for l in (cv_input.get("languages") or [])],
                "certifications": [{"name": c, "issuer": "", "year": ""} for c in (cv_input.get("certifications") or [])],
                "total_experience_years": cv_input.get("experience_years", 0),
                "personal_identity": {
                    "location": cv_input.get("location", ""),
                    "nationality": cv_input.get("citizenship", ""),
                },
                "experience": [],
                "education": [],
            })
    else:
        candidate = build_candidate_json()

    job = parse_job_v2(job_text, force_refresh=force_job_refresh)
    result = compute_ats_engine(candidate, job)

    blockers, explanations = check_hard_blockers(candidate, job, job_text)
    result["hard_blockers"] = blockers
    result["blocker_explanations"] = explanations
    result["ats_score"] = int(round(result["overall_ats"]))
    result["hits"] = result["gap_analysis"]["strengths"]
    result["gaps"] = result["gap_analysis"]["missing"]
    result["parsed_job"] = job
    result["parsed_cv"] = candidate

    return result


# ==============================================================================
# 8. LEGACY / HELPER FUNCTIONS
# ==============================================================================

def generate_tailored_cv(cv_text: str, job_text: str, gap_analysis: dict) -> str:
    missing = ", ".join(
        gap_analysis.get("gaps")
        or gap_analysis.get("gap_analysis", {}).get("missing")
        or []
    )
    prompt = f"""You are an executive resume writer. Tailor this CV for the job.
Integrate missing keywords naturally: {missing}
Do not fabricate experience.

Job: {job_text}

CV: {cv_text}"""
    response = _call_gemini(prompt)
    return response if response else "Generation failed. Check API key and limits."