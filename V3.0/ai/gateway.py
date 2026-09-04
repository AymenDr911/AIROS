"""AIROS V3 - AI Gateway (Slice 6, DEC-005 / ISS-004).

Verbatim port of the V2 ``services/cv_extractor.py`` Gemini core (the exact
model fallback chain, retry matrix, JSON cleaning/repair and post-processing),
with the V3 integration rules applied:

- ISS-004: the API key is INJECTED by the caller (config layer reads the env);
  the gateway never touches ``st.secrets`` or the process env itself.
- No Streamlit coupling: failures are raised as :class:`GatewayError` with a
  user-displayable message, exactly like the V2 ``st.error`` paths.
- DEC-005: the provider is behind an interface; the deterministic fallback is
  V2's own behavior - extraction failure returns a clean error and the user
  is directed to Manual Mode (never a silent provider swap).

Only stdlib is used for HTTP (urllib), matching V2 exactly.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# ==============================================================================
# 1. CORE GEMINI CONNECTOR (port of V2 cv_extractor.py, unchanged behavior)
# ==============================================================================
MODEL_FALLBACK_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]


class GatewayError(Exception):
    """Raised when the AI provider cannot complete a request (user-displayable)."""


def _list_supported_generate_models(api_key: str) -> List[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = payload.get("models", [])
            supported: List[str] = []
            for model in models:
                name = str(model.get("name", ""))
                methods = model.get("supportedGenerationMethods", [])
                if not name or "generateContent" not in methods:
                    continue
                short_name = name.split("models/")[-1]
                if short_name.startswith("gemini"):
                    supported.append(short_name)
            return supported
    except Exception:
        return []


def _resolve_model_chain(api_key: str) -> List[str]:
    available = _list_supported_generate_models(api_key)
    if not available:
        return MODEL_FALLBACK_CHAIN
    resolved: List[str] = [m for m in MODEL_FALLBACK_CHAIN if m in available]
    for m in available:
        if m not in resolved:
            resolved.append(m)
    return resolved


def _call_gemini(prompt: str, api_key: str, json_mode: bool = False, max_retries: int = 2) -> str | None:
    """V2 ``_call_gemini`` with the key injected (ISS-004) and GatewayError
    instead of ``st.error``. Returns the model text or raises GatewayError."""
    if not api_key:
        raise GatewayError(
            "GEMINI_API_KEY missing. Please add it to the .env file "
            "(server-side only; never in the web/ frontend)."
        )
    api_key = api_key.strip().strip("'\"")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    model_chain = _resolve_model_chain(api_key)
    if not model_chain:
        raise GatewayError("Gemini API Connection Failed. No compatible models found for generateContent.")

    errors: List[str] = []
    for model in model_chain:
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
                    errors.append(f"Model '{model}' returned no text candidates")
                    break
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="ignore")
                msg = f"Model '{model}' -> HTTP {e.code}: {error_body[:220]}"
                if e.code in (401, 403):
                    raise GatewayError(f"Gemini API Auth Error: {error_body[:400]}") from e
                elif e.code in (404, 400):
                    errors.append(msg)
                    break
                elif e.code in (503, 429):
                    errors.append(msg)
                    time.sleep(1.5 * attempt)
                    continue
                else:
                    errors.append(msg)
                    break
            except Exception as e:  # noqa: BLE001 - parity with V2 catch-all
                errors.append(f"Model '{model}' -> Exception: {str(e)}")
                time.sleep(1.0)
                continue

    summary = "\n".join(errors[-4:]) if errors else "No models attempted."
    raise GatewayError(f"Gemini API Connection Failed.\n{summary}")


# ==============================================================================
# 2. RESPONSE CLEANING / REPAIR (port of V2, unchanged)
# ==============================================================================
def _clean_json_response(raw_response: str) -> str:
    if not raw_response:
        return "{}"

    cleaned = raw_response.strip()

    # Remove markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)

    # Extract the biggest JSON-looking block
    match = re.search(r"(\{[\s\S]*\})", cleaned)
    if match:
        cleaned = match.group(1)

    # Common Gemini mistakes
    cleaned = re.sub(r",\s*}", "}", cleaned)          # trailing comma before }
    cleaned = re.sub(r",\s*]", "]", cleaned)          # trailing comma before ]
    cleaned = re.sub(r"}\s*{", "},{", cleaned)        # missing comma between objects
    cleaned = cleaned.replace("'", '"')               # single quotes -> double quotes

    # Remove control characters that sometimes appear (preserve newlines for now)
    cleaned = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)

    # Escape unescaped newlines/tabs inside JSON string values
    cleaned = _repair_unescaped_strings(cleaned)

    return cleaned


def _repair_unescaped_strings(text: str) -> str:
    """Walk through the JSON character-by-character and escape
    problematic characters (newlines, tabs, unescaped quotes)
    that appear inside string values."""
    result = []
    i = 0
    in_string = False
    length = len(text)

    while i < length:
        ch = text[i]

        if not in_string:
            if ch == '"':
                in_string = True
            result.append(ch)
            i += 1
            continue

        # We are inside a string
        if ch == "\\":
            # Escaped sequence - keep as-is
            result.append(ch)
            if i + 1 < length:
                i += 1
                result.append(text[i])
            i += 1
            continue

        if ch == '"':
            # Could be the real closing quote, or an unescaped interior quote.
            # Heuristic: if the next non-whitespace char is a structural JSON
            # token, this is the real closing quote.
            rest = text[i + 1:].lstrip()
            if not rest or rest[0] in ',:]}':
                in_string = False
                result.append(ch)
            else:
                result.append('\\"')
            i += 1
            continue

        if ch == "\n":
            result.append("\\n")
            i += 1
            continue

        if ch == "\r":
            result.append("\\r")
            i += 1
            continue

        if ch == "\t":
            result.append("\\t")
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


# ==============================================================================
# 3. RICH ONBOARDING EXTRACTION (port of V2, unchanged prompt + post-processing)
# ==============================================================================
PROMPT_PREAMBLE = """
You are a strict ATS CV parser. Your ONLY job is to extract information that is LITERALLY present in the CV text.

IMPORTANT: Return ONLY pure valid JSON. No markdown, no comments, no trailing commas, no single quotes.

OUTPUT JSON SCHEMA (follow exactly):
{
  "personal_identity": {
    "full_name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": "",
    "portfolio": "",
    "summary": ""
  },
  "career_stage_suggestion": "MUST be one of these exact strings: 'Student / Recent Graduate' | 'Looking for Internship' | 'Entry-Level Professional (0–2 years)' | 'Experienced Professional (3–8 years)' | 'Senior Expert / Manager (8+ years)' | 'Freelancer / Consultant' | 'Entrepreneur / Business Owner' | 'Career Transition / Changing Path'",
  "education": [
    {
      "degree": "",
      "field": "",
      "institution": "",
      "location": "",
      "start_year": "",
      "end_year": "",
      "description": ""
    }
  ],
  "professional_experience": [
    {
      "company": "",
      "role": "",
      "location": "",
      "start_date": "",
      "end_date": "",
      "currently_working": false,
      "description": "",
      "achievements": []
    }
  ],
  "technical_skills": [],
  "core_skills": [],
  "languages": [
    {
      "language": "",
      "level": ""
    }
  ],
  "certifications": [
    {
      "name": "",
      "issuer": "",
      "year": ""
    }
  ],
  "total_experience_years": 0
}

CRITICAL RULES FOR SKILLS (MUST FOLLOW):
- technical_skills and core_skills must come EXCLUSIVELY from a dedicated "Skills", "Technical Skills", "Competencies", "Expertise", "Key Skills" or similar section of the CV.
- If no clear dedicated Skills section exists -> return empty arrays: "technical_skills": [] and "core_skills": [].
- NEVER invent, infer, deduce, or create skills from experience, projects, summary, education, or job descriptions.
- NEVER add skills that are not written as a skill in the Skills section.
- technical_skills = only hard/technical items that appear in the Skills section.
- core_skills = only soft/transferable skills that appear in the Skills section.
- Keep the exact wording used in the CV (do not rephrase or expand).
- Both lists must be flat arrays of simple strings. No levels, no categories, no duplicates.

OTHER RULES:
- Return ONLY valid JSON.
- Include associative, NGO, volunteer, and civil-association roles inside "professional_experience" if they have responsibilities/dates.
- "certifications" must always exist (empty [] if none).
- "languages" must contain only spoken/written human languages (never programming languages or tools).
- Calculate "total_experience_years" including all professional, freelance, internship, and associative periods (count overlaps once, round up at 0.5).
- career_stage_suggestion MUST be an exact, verbatim match to one of the 8 listed options.
- Extract EVERY experience, education and certification that appears in the CV.
- If a field is missing, leave it empty (do not invent).

CV CONTENT:
"""

_TECH_KEYWORDS = {
    "python", "java", "javascript", "js", "typescript", "ts", "sql", "c++", "c#",
    "react", "vue", "angular", "node", "spring", "django", "flask", "docker",
    "kubernetes", "k8s", "aws", "azure", "git", "jenkins", "html", "css",
    "postgresql", "mysql", "mongodb", "power bi", "excel", "odoo", "sap",
    "erp", "mrp", "wms", "rest", "api", "microservices", "ci/cd"
}
_METHOD_KEYWORDS = {
    "agile", "scrum", "kanban", "waterfall", "pmo", "pmi", "pmp", "okr",
    "six sigma", "lean", "risk", "stakeholder", "governance", "gantt"
}
_PROG_KEYWORDS = {
    "python", "java", "javascript", "js", "typescript", "ts", "sql", "c++", "c#", "ruby",
    "php", "go", "rust", "scala", "kotlin", "swift", "docker", "kubernetes", "k8s",
    "aws", "azure", "git", "jenkins", "react", "vue", "angular", "node", "django",
    "flask", "spring", "laravel", ".net", "html", "css", "bash", "shell"
}


def extract_rich_profile_from_text(raw_text: str, api_key: str) -> Dict[str, Any]:
    """V2 ``extract_rich_profile`` text stage: prompt -> Gemini -> clean ->
    parse -> safe defaults -> skills mapping -> spoken-language filter.

    Raises GatewayError on provider failure; returns {} on unparsable output
    (V2 parity: the UI then offers Manual Mode).
    """
    if not raw_text or len(raw_text) < 50:
        raise GatewayError("Could not extract enough text from the uploaded CV(s).")

    prompt = PROMPT_PREAMBLE + raw_text
    response = _call_gemini(prompt, api_key, json_mode=True)
    if not response:
        return {}

    return _process_extraction(response)


def _process_extraction(response: str) -> Dict[str, Any]:
    """V2 response post-processing, unchanged (safe defaults, skill cleaning,
    structured skills mapping, spoken-language filtering)."""
    try:
        cleaned = _clean_json_response(response)
        data = json.loads(cleaned)

        if not isinstance(data, dict):
            data = {}

        # ---------- Safe defaults ----------
        data.setdefault("professional_experience", [])
        if not isinstance(data.get("professional_experience"), list):
            data["professional_experience"] = []

        data.setdefault("education", [])
        if not isinstance(data.get("education"), list):
            data["education"] = []

        data.setdefault("certifications", [])
        if not isinstance(data.get("certifications"), list):
            data["certifications"] = []

        data.setdefault("technical_skills", [])
        data.setdefault("core_skills", [])
        if not isinstance(data["technical_skills"], list):
            data["technical_skills"] = []
        if not isinstance(data["core_skills"], list):
            data["core_skills"] = []

        # ---------- Clean skill lists ----------
        def _clean_list(items):
            seen = set()
            result = []
            for item in items:
                if isinstance(item, str):
                    cleaned_item = item.strip()
                    if cleaned_item and cleaned_item.lower() not in seen:
                        seen.add(cleaned_item.lower())
                        result.append(cleaned_item)
            return result

        data["technical_skills"] = _clean_list(data["technical_skills"])
        data["core_skills"] = _clean_list(data["core_skills"])

        # ---------- Map to structured skills for the UI ----------
        technical = []
        methodologies = []
        tools = []

        for skill in data["technical_skills"]:
            s_lower = skill.lower()
            if any(kw in s_lower for kw in _METHOD_KEYWORDS):
                methodologies.append(skill)
            elif any(kw in s_lower for kw in _TECH_KEYWORDS):
                technical.append(skill)
            else:
                technical.append(skill)

        data["skills"] = {
            "technical": technical,
            "methodologies": methodologies,
            "tools": tools,
            "core": data["core_skills"],          # keep core skills accessible
        }

        # ---------- Filter programming languages out of spoken languages ----------
        if "languages" in data and isinstance(data["languages"], list):
            filtered_langs = []
            for entry in data["languages"]:
                if not isinstance(entry, dict):
                    continue
                lang_name = str(entry.get("language", "")).lower().strip()
                is_tech = lang_name and any(kw in lang_name for kw in _PROG_KEYWORDS)
                if lang_name and not is_tech:
                    filtered_langs.append(entry)
            data["languages"] = filtered_langs
        else:
            data["languages"] = []

        return data

    except json.JSONDecodeError as e:
        # Second-pass: try to isolate valid JSON by trimming at the error position
        try:
            error_pos = e.pos or 0
            cleaned = _clean_json_response(response)
            # Try truncating after the last complete top-level closing brace
            last_brace = cleaned.rfind("}", 0, error_pos + 200)
            if last_brace > 0:
                truncated = cleaned[:last_brace + 1]
                # Balance any unclosed arrays/objects
                open_sq = truncated.count("[") - truncated.count("]")
                open_cr = truncated.count("{") - truncated.count("}")
                truncated += "]" * max(open_sq, 0) + "}" * max(open_cr, 0)
                data = json.loads(truncated)
                if isinstance(data, dict):
                    # V2 parity: recovered response keeps safe defaults only
                    data.setdefault("professional_experience", [])
                    data.setdefault("education", [])
                    data.setdefault("certifications", [])
                    data.setdefault("technical_skills", [])
                    data.setdefault("core_skills", [])
                    return data
        except Exception:
            pass

        raise GatewayError(f"Failed to parse Gemini JSON response: {e}") from e
    except GatewayError:
        raise
    except Exception as e:  # noqa: BLE001 - parity with V2 catch-all
        raise GatewayError(f"Unexpected error while processing Gemini response: {e}") from e
