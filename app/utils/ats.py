import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import streamlit as st

# ==============================================================================
# 1. CORE AI CONNECTOR (Updated Models)
# ==============================================================================
MODEL_FALLBACK_CHAIN = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",  # Last resort
]

def _call_gemini(prompt: str, json_mode: bool = False, max_retries: int = 2) -> str | None:
    """Robust Gemini REST connector."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        st.error("GEMINI_API_KEY missing. Please add it to .streamlit/secrets.toml or environment variables.")
        return None

    api_key = api_key.strip().strip("'\"")

    payload = {
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
                with urllib.request.urlopen(request, timeout=30) as response:
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
                elif e.code in (404, 400):
                    break
                elif e.code in (503, 429):
                    time.sleep(1.5 * attempt)
                    continue
                else:
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
# 2. PARSING FUNCTIONS (unchanged except minor robustness)
# ==============================================================================
def parse_cv(cv_text: str, force_refresh: bool = False) -> dict:
    cv_hash = _get_text_hash(cv_text)
    cache_key = f"parsed_cv_{cv_hash}"
    if not force_refresh and cache_key in st.session_state:
        cached = st.session_state[cache_key]
        if not cached.get("_api_error"):
            return cached

    prompt = f"""
Extract structured recruitment entities from this CV as valid JSON:
{{
    "mandatory_skills": ["core", "domain", "skills"],
    "technical_skills": ["tools", "technologies", "platforms"],
    "experience_years": 0,
    "certifications": ["cert1", "cert2"],
    "languages": ["English", "German"],
    "keywords": ["industry", "methodology", "terms"],
    "has_ats_formatting": true,
    "notice_period": 30,
    "location": "Tunisia",
    "citizenship": "Tunisian"
}}
STRICT RULES: Return ONLY valid JSON. Extract every certification and language mentioned.
CV Text: {cv_text}
"""
    response = _call_gemini(prompt, json_mode=True)
    default_data = {
        "mandatory_skills": [], "technical_skills": [], "experience_years": 0,
        "certifications": [], "languages": [], "keywords": [],
        "has_ats_formatting": True, "notice_period": 30, "location": "",
        "citizenship": "", "_api_error": True
    }
    if response:
        try:
            cleaned = _clean_json_response(response)
            parsed = json.loads(cleaned)
            result = {
                "mandatory_skills": parsed.get("mandatory_skills") or [],
                "technical_skills": parsed.get("technical_skills") or [],
                "experience_years": int(parsed.get("experience_years") or 0),
                "certifications": parsed.get("certifications") or [],
                "languages": parsed.get("languages") or [],
                "keywords": parsed.get("keywords") or [],
                "has_ats_formatting": bool(parsed.get("has_ats_formatting", True)),
                "notice_period": int(parsed.get("notice_period") or 30),
                "location": parsed.get("location", ""),
                "citizenship": parsed.get("citizenship", ""),
                "_api_error": False,
            }
            st.session_state[cache_key] = result
            return result
        except Exception:
            pass
    return default_data


def parse_job(job_text: str, force_refresh: bool = False) -> dict:
    # ... (keep your original parse_job function unchanged)
    job_hash = _get_text_hash(job_text)
    cache_key = f"parsed_job_{job_hash}"
    if not force_refresh and cache_key in st.session_state:
        cached = st.session_state[cache_key]
        if not cached.get("_api_error"):
            return cached

    prompt = f"""
Extract key hiring requirements from this Job Description as valid JSON:
{{
    "mandatory_skills": ["must-have", "skills"],
    "technical_skills": ["required", "tools"],
    "required_experience_years": 0,
    "required_certifications": ["required", "certs"],
    "required_languages": ["required", "languages"],
    "keywords": ["important", "terms"]
}}
CRITICAL: Break into short atomic skills. Return ONLY valid JSON.
Job Description: {job_text}
"""
    response = _call_gemini(prompt, json_mode=True)
    default_data = {
        "mandatory_skills": [], "technical_skills": [], "required_experience_years": 0,
        "required_certifications": [], "required_languages": [], "keywords": [],
        "_api_error": True
    }
    if response:
        try:
            cleaned = _clean_json_response(response)
            parsed = json.loads(cleaned)
            result = {
                "mandatory_skills": parsed.get("mandatory_skills") or [],
                "technical_skills": parsed.get("technical_skills") or [],
                "required_experience_years": int(parsed.get("required_experience_years") or 0),
                "required_certifications": parsed.get("required_certifications") or [],
                "required_languages": parsed.get("required_languages") or [],
                "keywords": parsed.get("keywords") or [],
                "_api_error": False,
            }
            st.session_state[cache_key] = result
            return result
        except Exception:
            pass
    return default_data


# ==============================================================================
# 3. ADVANCED HARD BLOCKERS (Recruitment Expert Logic)
# ==============================================================================
def check_hard_blockers(parsed_cv: dict, parsed_job: dict, raw_job_text: str = "") -> tuple[list[str], list[str]]:
    """Real-world hard blocker detection."""
    blockers = []
    explanations = []
    job_lower = (raw_job_text or "").lower()

    # API Failure
    if parsed_job.get("_api_error") or parsed_cv.get("_api_error"):
        blockers.append("API Failure")
        explanations.append("Unable to analyze job requirements properly.")
        return blockers, explanations

    # Visa / EU Work Authorization
    if any(phrase in job_lower for phrase in ["eu citizen", "work permit", "no visa", "visa sponsorship", "sponsorship not", "eligible to work in", "right to work"]):
        if "no visa" in job_lower or "sponsorship" in job_lower:
            blockers.append("No Visa Sponsorship")
            explanations.append("The job does not offer visa sponsorship. Candidate is based outside EU (Tunisia/MENA) → strong barrier.")

    # Critical Local Language
    req_langs = [l.lower().strip() for l in parsed_job.get("required_languages", [])]
    cv_langs = " ".join([l.lower().strip() for l in parsed_cv.get("languages", [])]).lower()
    critical_langs = ["german", "dutch", "nederlands", "swedish", "deutsch"]
    for lang in req_langs:
        if lang in critical_langs and lang not in cv_langs:
            blockers.append(f"Local Language: {lang.capitalize()}")
            explanations.append(f"Role requires strong {lang.capitalize()} proficiency. CV shows English/German but may not meet the expected level.")

    # Notice Period + Relocation
    if any(phrase in job_lower for phrase in ["immediate", "1 month", "within 1 month", "asap", "short notice"]):
        cv_notice = parsed_cv.get("notice_period", 60)
        if cv_notice > 45 or "tunisia" in str(parsed_cv.get("location", "")).lower():
            blockers.append("Relocation / Notice Period")
            explanations.append("Job requires very fast start. Candidate location (Tunisia/MENA) + notice period makes it unrealistic.")

    # Experience
    cv_exp = int(parsed_cv.get("experience_years") or 0)
    req_exp = int(parsed_job.get("required_experience_years") or 0)
    if req_exp > 0 and cv_exp < req_exp * 0.75:
        blockers.append("Major Experience Gap")
        explanations.append(f"Requires ~{req_exp} years. Candidate has {cv_exp} years.")

    return blockers, explanations


# ==============================================================================
# 4. SCORING & TAILORING (Improved)
# ==============================================================================
def _is_token_in_cv(target: str, cv_tokens: set[str]) -> bool:
    t = target.lower().strip()
    if not t: return True
    if t in cv_tokens: return True
    pattern = r"(?<!\w)" + re.escape(t) + r"(?!\w)"
    return any(re.search(pattern, cvt) for cvt in cv_tokens if len(t) >= 3)


def compute_ats_score(parsed_cv: dict, parsed_job: dict) -> dict:
    # (Use the improved version from previous messages - with proper rounding)
    total_requirements = len(parsed_job.get("mandatory_skills", [])) + len(parsed_job.get("technical_skills", [])) + \
                         len(parsed_job.get("required_certifications", [])) + len(parsed_job.get("keywords", [])) + \
                         len(parsed_job.get("required_languages", []))

    if total_requirements == 0 or parsed_job.get("_api_error") or parsed_cv.get("_api_error"):
        return {"overall_score": 0.0, "sub_scores": {k: 0.0 for k in ["mandatory_skills","technical_skills","experience","certifications","keywords","languages","formatting"]}, "matched_skills": [], "missing_skills": []}

    all_cv_tokens = set([s.lower().strip() for s in parsed_cv.get("mandatory_skills", [])] +
                        [s.lower().strip() for s in parsed_cv.get("technical_skills", [])] +
                        [c.lower().strip() for c in parsed_cv.get("certifications", [])] +
                        [k.lower().strip() for k in parsed_cv.get("keywords", [])] +
                        [l.lower().strip() for l in parsed_cv.get("languages", [])])

    def calculate_category_match(job_list):
        if not job_list: return 100.0, [], []
        matched = [item for item in job_list if _is_token_in_cv(item, all_cv_tokens)]
        missing = [item for item in job_list if item not in matched]
        return round((len(matched) / len(job_list)) * 100.0, 1), matched, missing

    mand_score, mand_m, mand_g = calculate_category_match(parsed_job.get("mandatory_skills", []))
    tech_score, tech_m, tech_g = calculate_category_match(parsed_job.get("technical_skills", []))
    cert_score, cert_m, cert_g = calculate_category_match(parsed_job.get("required_certifications", []))
    kw_score, kw_m, kw_g = calculate_category_match(parsed_job.get("keywords", []))
    lang_score, lang_m, lang_g = calculate_category_match(parsed_job.get("required_languages", []))

    cv_exp = int(parsed_cv.get("experience_years") or 0)
    req_exp = int(parsed_job.get("required_experience_years") or 0)
    exp_score = 100.0 if req_exp == 0 or cv_exp >= req_exp else round((cv_exp / max(req_exp, 1)) * 100.0, 1)

    format_score = 100.0 if parsed_cv.get("has_ats_formatting", True) else 60.0

    overall_score = round(
        mand_score*0.30 + tech_score*0.25 + exp_score*0.15 + cert_score*0.10 +
        kw_score*0.10 + lang_score*0.05 + format_score*0.05, 1
    )

    return {
        "overall_score": overall_score,
        "sub_scores": {
            "mandatory_skills": mand_score, "technical_skills": tech_score,
            "experience": exp_score, "certifications": cert_score,
            "keywords": kw_score, "languages": lang_score, "formatting": format_score
        },
        "matched_skills": sorted(set(mand_m + tech_m + cert_m + kw_m + lang_m)),
        "missing_skills": sorted(set(mand_g + tech_g + cert_g + kw_g + lang_g)),
    }


def generate_tailored_cv(cv_text: str, job_text: str, gap_analysis: dict) -> str:
    missing = ", ".join(gap_analysis.get("gaps", []))
    prompt = f"""You are an executive resume writer. Tailor this CV for the job.
Integrate missing keywords naturally: {missing}
Do not fabricate experience.

Job: {job_text}
CV: {cv_text}"""
    response = _call_gemini(prompt)
    return response if response else "Generation failed. Check API key and limits."


def calculate_ats_gap(cv_input: str | dict, job_text: str, force_job_refresh: bool = False) -> dict:
    if isinstance(cv_input, dict):
        parsed_cv = cv_input
    else:
        parsed_cv = parse_cv(cv_input)

    parsed_job = parse_job(job_text, force_refresh=force_job_refresh)
    scoring = compute_ats_score(parsed_cv, parsed_job)
    hard_blockers, explanations = check_hard_blockers(parsed_cv, parsed_job, job_text)

    return {
        "ats_score": int(scoring.get("overall_score", 0)),
        "hard_blockers": hard_blockers,
        "blocker_explanations": explanations,
        "hits": scoring.get("matched_skills", []),
        "gaps": scoring.get("missing_skills", []),
        "sub_scores": scoring.get("sub_scores", {}),
        "parsed_cv": parsed_cv,
        "parsed_job": parsed_job,
    }