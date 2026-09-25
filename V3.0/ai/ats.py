"""AIROS V3 - Deterministic ATS Engine (DEC-006 increment).

Streamlit-free port of the V2 ``app/utils/ats.py`` (the "Advanced ATS Engine"):
one Gemini call parses the Job Description (through the V3 AI gateway,
DEC-005/ISS-004), then every scoring and gating rule is DETERMINISTIC - same
input always yields the same number (R06: scores are derived, never sourced):

- ``parse_job_v2``      - ONE Gemini call (json_mode) -> structured job JSON.
- ``check_hard_blockers`` - V2 deterministic blockers (visa/work auth, local
  language, fast start + location, major experience gap).
- ``compute_ats_engine`` - V2 component scores with the EXACT V2 weights:
  technical 0.30 / experience 0.25 / methodologies 0.10 / tools 0.10 /
  languages 0.10 / education 0.05 / certifications 0.05 / industry 0.05.
- ``classify_threshold`` - the ATS analyzer gating (revised Spec B, CHG-017):
  <70 hard reject, 70-79 soft reject, 80-89 manual approval gate, >=90 strong
  match.  Every possible response is deterministic with the shape {band, title,
  message, next_step, proceed}; hard blockers force the NO path and are listed
  explicitly (CHG-017).

No paid dependencies (reuses the gateway's free Gemini core); the API key is
injected by the caller (ISS-004); no Streamlit/session coupling.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from ai.gateway import _call_gemini, _clean_json_response, GatewayError

# ==============================================================================
# 1. WEIGHTS + EVIDENCE (V2 verbatim)
# ==============================================================================

DEFAULT_WEIGHTS: Dict[str, float] = {
    "technical_skills": 0.30,
    "experience": 0.25,
    "methodologies": 0.10,
    "tools": 0.10,
    "languages": 0.10,
    "education": 0.05,
    "certifications": 0.05,
    "industry": 0.05,
}

EVIDENCE_STARS = {
    5: "★★★★★",
    4: "★★★★☆",
    3: "★★★☆☆",
    2: "★★☆☆☆",
    1: "★☆☆☆☆",
    0: "☆☆☆☆☆",
}


def _token_match(target: str, tokens: Set[str]) -> bool:
    """V2: exact or word-boundary token match (len>=3)."""
    t = target.lower().strip()
    if not t:
        return True
    if t in tokens:
        return True
    pattern = r"(?<!\w)" + re.escape(t) + r"(?!\w)"
    return any(re.search(pattern, tok) for tok in tokens if len(t) >= 3)


def _evidence_level(item: str, candidate: Dict[str, Any], category: str) -> int:
    """V2 evidence level system (0-5)."""
    item_l = item.lower().strip()
    if not item_l:
        return 5

    skills = candidate.get("skills") or {}
    technical = {s.lower() for s in skills.get("technical") or []}
    methodologies = {s.lower() for s in skills.get("methodologies") or []}
    tools = {s.lower() for s in skills.get("tools") or []}
    cert_names = {c.get("name", "").lower() for c in candidate.get("certifications") or []}
    lang_names = {l.get("language", "").lower() for l in candidate.get("languages") or []}

    # --- certifications (fuzzy, V2 short forms) ---
    if category == "certifications":
        if item_l in cert_names:
            return 5
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
    if category == "languages":
        for lang_name in lang_names:
            if item_l == lang_name or item_l in lang_name or lang_name in item_l:
                return 5

    # --- token fallback ---
    all_tokens = candidate.get("all_tokens") or set()
    if _token_match(item_l, all_tokens):
        return 4
    if item_l in all_tokens:
        return 3
    for tok in all_tokens:
        if len(item_l) >= 4 and (item_l in tok or tok in item_l):
            return 2
    return 0


# ==============================================================================
# 2. COMPONENT SCORING (V2 verbatim)
# ==============================================================================

def _score_list_match(
    required: List[str],
    candidate: Dict[str, Any],
    category: str,
) -> Tuple[float, List[Dict[str, Any]], List[str]]:
    """V2 ``_score_list_match``: fraction of required items with level>=2."""
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
    """V2 ``_score_experience`` (years curve, verbatim)."""
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


_DEGREE_MAP = {
    "phd": 5, "doctorate": 5, "master": 4, "msc": 4, "mba": 4,
    "bachelor": 3, "bsc": 3, "ba": 3, "licence": 3,
    "associate": 2, "diploma": 2, "high school": 1,
}


def _score_education(candidate: Dict[str, Any], job: Dict[str, Any]) -> float:
    """V2 ``_score_education``: degree level (70%) + preferred fields (30%)."""
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

    required_level = 0
    for k, v in _DEGREE_MAP.items():
        if k in min_degree:
            required_level = v
            break

    best_cand_level = 0
    best_field_match = False

    for edu in cand_edu:
        if not isinstance(edu, dict):
            continue
        deg = (edu.get("degree") or "").lower()
        field = (edu.get("field") or edu.get("field_of_study") or "").lower()
        for k, v in _DEGREE_MAP.items():
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


_LEVEL_ORDER = {
    "a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6,
    "native": 7, "fluent": 6, "professional": 5,
}


def _score_languages(candidate: Dict[str, Any], job: Dict[str, Any]) -> Tuple[float, List[Dict], List[str]]:
    """V2 ``_score_languages`` (verbatim)."""
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

    for req in req_langs:
        lang = (req.get("language") or "").strip()
        req_level = (req.get("level") or "").lower()
        lang_l = lang.lower()

        if lang_l in cand_map:
            cand_level = cand_map[lang_l]
            req_val = _LEVEL_ORDER.get(req_level, 0)
            cand_val = _LEVEL_ORDER.get(cand_level, 4)

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
    """V2 ``_score_industry`` (verbatim)."""
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


# ==============================================================================
# 3. HARD BLOCKERS (V2 verbatim)
# ==============================================================================

_POSITIVE_VISA = [
    "visa sponsorship", "sponsorship provided", "blue card",
    "relocation package", "relocation support", "we sponsor",
    "full visa", "visa support", "work permit support",
]
_NEGATIVE_VISA = [
    "no visa sponsorship", "sponsorship not available", "no sponsorship",
    "must already have the right to work", "must have the right to work",
    "eu citizens only", "only eu citizens", "no visa",
]
_LOCAL_LANGS = {"german", "dutch", "nederlands", "swedish", "deutsch", "french", "français"}
# Canonical key per critical local language so German==Deutsch and
# Dutch==Nederlands are compared as ONE language in the hard-bottleneck gate.
_LOCAL_LANG_ALIASES = {
    "german": "german", "deutsch": "german",
    "dutch": "dutch", "nederlands": "dutch",
    "french": "french", "français": "french",
    "swedish": "swedish", "schwedisch": "swedish",
}
_NON_EU_HINTS = ("tunisia", "mena", "africa", "non-eu", "asia")
_FAST_START = ("immediate", "asap", "1 month", "within 1 month", "short notice")

# Aliases per canonical local language - used to find the language mention in
# the RAW job text (raw text may say "Deutsch"/"Nederlands" while the engine
# canonicalises to german/dutch).
_LOCAL_LANG_ALIAS_GROUPS = {
    "german": ("german", "deutsch", "deutschkenntnisse", "german language"),
    "dutch": ("dutch", "nederlands", "dutch language"),
    "french": ("french", "français", "french language"),
    "swedish": ("swedish", "schwedisch"),
}

# Explicit level signals that MAY qualify for a hard language-level bottleneck.
# ONLY explicit CEFR-level statements count: A1..C2 codes and high-signal
# nativelike statements.  Words like "fluent", "good", "working knowledge"
# are deliberately NOT a CEFR level - they must NEVER create a hard C1
# bottleneck by themselves (user report: "fluent German" falsely blocked a B1
# profile as "C1").
_LOCAL_LEVEL_SIGNALS: List[Tuple[str, Tuple[str, ...]]] = [
    ("c2", ("c2", "native", "mother tongue", "muttersprach")),
    ("c1", ("c1",)),
    ("b2", ("b2",)),
    ("b1", ("b1",)),
    ("a2", ("a2",)),
    ("a1", ("a1",)),
]

# Maximum distance (characters) between a language mention and a level token
# for the level to be attributed to that language.  The same-sentence scope
# and the "another language between" guard keep this from over-reaching.
_LOCAL_LEVEL_PROXIMITY = 50

# Other spoken languages used ONLY as a reference so a level stated for
# ANOTHER language (e.g. "English at C1") is never attributed to the target
# language when that other language is mentioned between them.
_OTHER_LANG_REFERENCES: Tuple[str, ...] = (
    "english", "spanish", "italian", "portuguese", "polish", "czech",
    "romanian", "turkish", "arabic", "chinese", "mandarin", "japanese",
    "korean", "russian", "greek", "danish", "norwegian", "finnish",
    "ukrainian", "hindi",
)


def _canon_language(name: Any) -> str:
    """Canonical form of a critical local language (verbatim otherwise)."""
    cleaned = str(name or "").strip().lower()
    return _LOCAL_LANG_ALIASES.get(cleaned, cleaned)


def _stated_language_level(raw_job_text: str, lang_name: str) -> Optional[Tuple[str, str]]:
    """Deterministic explicit-level extraction from the RAW job text.

    Returns ``(CEFR_UPPER, evidence_sentence)`` ONLY when the raw text states
    an EXPLICIT CEFR-level token for the given canonical local language:

    - the level must be in the SAME sentence as the language mention;
    - it must be the NEAREST level token to that mention; and
    - it is skipped when ANOTHER language name sits between the mention and
      the level token (that level belongs to the other language).

    Generic proficiency words ("fluent", "good", "working knowledge", ...) are
    deliberately NOT treated as a CEFR level (user report: a "fluent German"
    offer must not hard-block a B1 profile as "C1").

    Returns ``None`` when no explicit level is stated - the engine then MUST
    NOT invent a level (fix for the reported "C1 German" false blocker).
    """
    text = (raw_job_text or "").lower()
    if not text:
        return None
    own_aliases = _LOCAL_LANG_ALIAS_GROUPS.get(lang_name, (lang_name,))
    other_aliases = tuple(
        a
        for group in _LOCAL_LANG_ALIAS_GROUPS.values()
        for a in group
        if _canon_language(a) != lang_name
    ) + _OTHER_LANG_REFERENCES
    best: Optional[Tuple[int, str, str]] = None

    def _alias_pattern(alias: str) -> str:
        # Standalone alias; excludes letter/digit/hyphen right after so
        # "german-speaking" / "german-english" are not treated as the language.
        return r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9-])"

    for alias in own_aliases:
        for m in re.finditer(_alias_pattern(alias), text):
            # Sentence span that contains this language mention.
            start = text.rfind(".", 0, m.start()) + 1
            for sep in ("!", "?", "\n"):
                idx = text.rfind(sep, 0, m.start())
                if idx + 1 > start:
                    start = idx + 1
            end = len(text)
            for sep in (".", "!", "?", "\n"):
                idx = text.find(sep, m.end())
                if idx != -1 and idx < end:
                    end = idx
            sentence = text[start:end]

            other_positions = [
                om.start()
                for oa in other_aliases
                for om in re.finditer(_alias_pattern(oa), sentence)
            ]

            for cefr, tokens in _LOCAL_LEVEL_SIGNALS:
                for tok in sorted(tokens, key=len, reverse=True):
                    for tm in re.finditer(
                        r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", sentence
                    ):
                        lo = min(tm.start(), m.start())
                        hi = max(tm.end(), m.end())
                        if any(lo < p < hi for p in other_positions):
                            continue
                        dist = min(abs(tm.start() - m.start()), abs(tm.end() - m.start()))
                        if dist <= _LOCAL_LEVEL_PROXIMITY and (best is None or dist < best[0]):
                            best = (dist, cefr, sentence.strip())

    if best is None:
        return None
    return best[1].upper(), best[2][:160]


def _visa_signals(raw_job_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Deterministic visa-sponsorship signal detection on the RAW JD text.

    Returns ``(positive_support, negative_phrase, positive_phrase)``.
    Negative wording ("EU citizens only", "no visa sponsorship", ...) only
    blocks a non-EU candidate when NO clear sponsorship signal exists; a
    clear positive signal ("visa sponsorship", "blue card", ...) overrides
    the negative wording AND is surfaced to the user via ``visa_note``.
    """
    job_lower = (raw_job_text or "").lower()
    positive = next((p for p in _POSITIVE_VISA if p in job_lower), None)
    negative = next((n for n in _NEGATIVE_VISA if n in job_lower), None)
    return (positive is not None, negative, positive)


def check_hard_blockers(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    raw_job_text: str = "",
) -> Tuple[List[str], List[str]]:
    """V2 deterministic hard blockers: visa, local language (+ required
    level), fast start, gap."""
    blockers: List[str] = []
    explanations: List[str] = []
    job_lower = (raw_job_text or "").lower()

    if job.get("_api_error"):
        blockers.append("API Failure")
        explanations.append("Unable to analyse job requirements properly.")
        return blockers, explanations

    # ---------- VISA / WORK AUTHORIZATION (V2 rule, clarified) ----------
    # "EU citizens only" / "no sponsorship" wording blocks a non-EU candidate
    # ONLY when the company does NOT clearly indicate visa sponsorship.  A
    # clear positive signal overrides the negative wording, and the positive
    # signal is reported to the user via ``visa_note`` in calculate_ats_gap.
    has_positive, negative_phrase, _ = _visa_signals(raw_job_text)

    if negative_phrase and not has_positive:
        loc = (candidate.get("location") or "").lower()
        nat = (candidate.get("nationality") or "").lower()
        if any(x in loc or x in nat for x in _NON_EU_HINTS):
            blockers.append("No Visa Sponsorship")
            explanations.append(
                f'The job states "{negative_phrase}" and does not offer visa sponsorship. '
                "Candidate location/nationality indicates a strong barrier."
            )

    # ---------- LOCAL LANGUAGE (+ REQUIRED LEVEL) ----------
    # V2 blocked when a local language was absent from the profile.  Revised
    # (user verdict 2): the required LEVEL is enforced too - but ONLY when the
    # RAW JD explicitly states a level (deterministic; never a Gemini-guessed
    # level, which would wrongly hard-block a below-level candidate).
    cand_lang_map = {
        _canon_language(l.get("language")): (l.get("level") or "").lower()
        for l in candidate.get("languages") or []
    }
    for lang_req in job.get("languages") or []:
        # Canonical key: "Deutsch" and "German" are the SAME language, and
        # "Nederlands" and "Dutch" are the SAME language (user verdicts 1/2).
        lang_name = _canon_language(lang_req.get("language"))
        if lang_name not in _LOCAL_LANGS:
            continue
        display = (lang_req.get("language") or lang_name).title()
        if lang_name not in cand_lang_map:
            blockers.append(f"Local Language: {display}")
            explanations.append(
                f"Role requires strong {display} proficiency "
                "which is not present in the candidate profile."
            )
            continue
        cand_level = cand_lang_map[lang_name]
        # Hard language-level bottleneck fires ONLY when the raw JD explicitly
        # states a CEFR level for this language (deterministic, never invented;
        # evidence sentence quoted so the user can verify - user report: a B1
        # candidate must not be blocked by a Gemini-parsed "C1" guess or by a
        # generic word like "fluent").
        stated = _stated_language_level(raw_job_text, lang_name)
        if stated:
            stated_cefr, evidence = stated
            req_val = _LEVEL_ORDER.get(stated_cefr.lower(), 0)
            cand_val = _LEVEL_ORDER.get(cand_level, 0)
            if cand_val and cand_val < req_val:
                blockers.append(f"Local Language Level: {display}")
                shown = f' ("{evidence}")' if evidence else ""
                explanations.append(
                    f"The offer explicitly states {display} at {stated_cefr} level or higher{shown}; "
                    f"your profile lists {cand_level.upper()}. This hard requirement is not met."
                )
            elif not cand_val:
                blockers.append(f"Local Language Level: {display}")
                explanations.append(
                    f"The offer explicitly states {display} at {stated_cefr} level or higher; "
                    "your profile lists the language without a level. This hard requirement is not proven."
                )

    # ---------- FAST START + LOCATION ----------
    if any(p in job_lower for p in _FAST_START):
        loc = (candidate.get("location") or "").lower()
        if "tunisia" in loc or "mena" in loc:
            blockers.append("Relocation / Notice Period")
            explanations.append(
                "Job requires a very fast start. Candidate location makes immediate availability unrealistic."
            )

    # ---------- MAJOR EXPERIENCE GAP ----------
    cand_years = int(candidate.get("total_experience_years") or 0)
    req_years = int((job.get("experience") or {}).get("min_years") or 0)
    if req_years > 0 and cand_years < req_years * 0.70:
        blockers.append("Major Experience Gap")
        explanations.append(
            f"Role requires ~{req_years}+ years. Candidate has approximately {cand_years} years."
        )

    return blockers, explanations


# ==============================================================================
# 4. CANDIDATE JSON BUILDER (V2 port; reads a V3 profiles row)
# ==============================================================================

def _year(token: str) -> Optional[int]:
    token = str(token or "").strip()
    if not token:
        return None
    low = token.lower()
    if low in ("present", "now", "current", "today", "ongoing"):
        return date.today().year
    m = re.findall(r"\b(1\d{3}|20\d{2})\b", token)
    return int(m[-1]) if m else None


def _total_experience_years(experience: Any) -> int:
    """Sum role durations (V2 stored this on the profile; V3 derives it).
    Conservative, capped at 40, open-ended roles count up to the current year."""
    total = 0.0
    if isinstance(experience, list):
        for exp in experience:
            if not isinstance(exp, dict):
                continue
            sy, ey = _year(exp.get("start_date")), _year(exp.get("end_date"))
            if sy is None:
                continue
            ey = ey or date.today().year
            if ey < sy:
                continue
            total += float(ey - sy)
    return int(min(total, 40.0))


def build_candidate_json(profile: Dict[str, Any]) -> Dict[str, Any]:
    """V2 ``build_candidate_json`` adapted to the V3 profiles row shape:
    identity/education/experience/skills/languages/certifications."""
    identity = profile.get("identity") or profile.get("personal_identity") or {}
    if not isinstance(identity, dict):
        identity = {}

    skills_raw = profile.get("skills") or {}
    if not isinstance(skills_raw, dict):
        skills_raw = {}
    # V3 taxonomy (migration keys) -> V2 engine categories; tools were merged
    # into TECHNICAL by the migration transform (documented V3 change).
    technical = [str(s).strip() for s in (skills_raw.get("TECHNICAL") or []) if str(s).strip()]
    methodologies = [str(s).strip() for s in (skills_raw.get("MANAGEMENT") or []) if str(s).strip()]
    # TOOLS key is not present in stored V3 profiles (tools merge into
    # TECHNICAL), but the post-generation ATS re-scoring builds this candidate
    # from the GENERATED CV's structured skills and needs every category
    # represented so the recomputed score reflects the document faithfully.
    tools = [str(s).strip() for s in (skills_raw.get("TOOLS") or []) if str(s).strip()]
    # Also surface the section items (post-Slice6 storage) into the token pool.
    section_items: List[str] = []
    for sec in skills_raw.get("sections") or []:
        if isinstance(sec, dict):
            for item in sec.get("items") or []:
                if isinstance(item, str) and item.strip():
                    section_items.append(item.strip())
    technical = list(dict.fromkeys(technical + section_items))

    education = [
        {
            "degree": str(e.get("degree") or ""),
            "field": str(e.get("field_of_study") or e.get("field") or ""),
            "institution": str(e.get("institution") or ""),
        }
        for e in (profile.get("education") or [])
        if isinstance(e, dict)
    ]
    experience = [e for e in (profile.get("experience") or []) if isinstance(e, dict)]
    languages = []
    for lang in profile.get("languages") or []:
        if isinstance(lang, dict):
            languages.append({
                "language": str(lang.get("language") or "").strip(),
                "level": str(lang.get("level") or "").strip(),
            })
        elif isinstance(lang, str) and lang.strip():
            languages.append({"language": lang.strip(), "level": ""})
    certifications = [
        {
            "name": str(c.get("name") or "").strip(),
            "issuer": str(c.get("issuer") or "").strip(),
            "year": str(c.get("year") or "").strip(),
        }
        for c in (profile.get("certifications") or [])
        if isinstance(c, dict)
    ]

    total_years = _total_experience_years(experience)

    # all_tokens: skills + languages + certs + experience descriptions (V2).
    tokens: Set[str] = set()
    for item in technical + methodologies + tools:
        if item:
            tokens.add(item.lower().strip())
    for lang in languages:
        if lang.get("language"):
            tokens.add(lang["language"].lower().strip())
    for cert in certifications:
        if cert.get("name"):
            tokens.add(cert["name"].lower().strip())
    for exp in experience:
        desc = str(exp.get("description") or "") + " " + " ".join(str(a) for a in (exp.get("achievements") or []) if isinstance(a, str))
        for word in re.findall(r"[A-Za-z][A-Za-z0-9\+\#\.]{2,}", desc):
            tokens.add(word.lower())

    return {
        "personal_identity": identity,
        "location": str(identity.get("city") or identity.get("location") or ""),
        "nationality": str(identity.get("nationality") or ""),
        "total_experience_years": total_years,
        "skills": {
            "technical": technical,
            "methodologies": methodologies,
            "tools": tools,
        },
        "education": education,
        "experience": experience,
        "languages": languages,
        "certifications": certifications,
        "industry_hints": [],
        # V2 parity: SORTED LIST (V2 ats.py returns sorted(_build_all_tokens(...))).
        # A list (not a set) keeps the candidate JSON-serializable for the
        # Document Engine's json.dumps() - a set here crashed every generation
        # with "TypeError: Object of type set is not JSON serializable".
        "all_tokens": sorted(tokens),
    }


# ==============================================================================
# 5. JOB JSON - GEMINI ONE CALL ONLY (V2 prompt through the V3 gateway)
# ==============================================================================

_JD_CACHE: Dict[str, Dict[str, Any]] = {}

_JD_SCHEMA = """{
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
  "recruiter_contact": {"name": "", "position": "", "email": "", "linkedin_url": "", "phone": ""},
  "visa_sponsorship": {"support": "Yes | No | Not mentioned", "evidence": "", "notes": ""},
  "work_authorization": {"requirement": "Must already have right to work | Sponsorship available | Not mentioned", "evidence": ""},
  "required_skills": {"technical": [], "methodologies": [], "tools": []},
  "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
  "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
  "education": {"min_degree": "", "preferred_fields": []},
  "languages": [{"language": "", "level": "", "required": true, "type": "spoken | programming", "evidence": ""}],
  "certifications": [],
  "responsibilities": [],
  "keywords": [],
  "location_requirements": {"remote": false, "hybrid": false, "on_site": false, "cities_or_countries": [], "relocation_support": "Yes | No | Not mentioned"}
}"""

_JD_PROMPT = f"""
You are a senior recruitment analyst specialized in precise, non-hallucinated job parsing.
Extract a structured job profile from the Job Description below.
Return ONLY valid JSON that strictly follows the schema. Never invent requirements that are not clearly present.

OUTPUT SCHEMA (strict - follow exactly):
{_JD_SCHEMA}

STRICT RULES (must follow):
0. COMPANY & LOCATION (very important)
   - company_name: Extract the real hiring company name (e.g. "Siemens AG", "BMW Group", "Google").
     Never put the job board (LinkedIn, Indeed, StepStone...) as company_name.
   - location: City or region where the job is based (e.g. "Munich", "Paris", "Remote - Germany").
   - country: Full country name or ISO code if clearly stated (e.g. "Germany", "France", "Remote").
   - If the information is not present, leave the field as empty string "".
   - recruiter_contact: the INDIVIDUAL hiring contact when the JD names one
     (e.g. "Contact: Anna Mueller, Senior Talent Acquisition,
     anna.mueller@company.com, +49 170 1234567, linkedin.com/in/..."). Copy each field
     verbatim; NEVER invent a name/email/phone. Generic addresses (info@,
     careers@, jobs@, hr@...) are NOT an individual recruiter - leave
     recruiter_contact empty when only those appear. phone is optional.

1. VISA / WORK AUTHORIZATION (critical)
   - Decide "Yes", "No" or "Not mentioned" based only on explicit statements.
   - Positive signals: "visa sponsorship", "we sponsor", "Blue Card", "relocation package", "work permit support", etc.
   - Negative signals: "no visa sponsorship", "must already have the right to work", "EU citizens only", "no sponsorship", etc.
   - If both positive and negative signals exist, prefer the most restrictive one and explain in notes.
   - Never assume sponsorship just because the company is international.

2. TECHNICAL SKILLS - solid logic, zero repetition
   - Break every skill into short atomic items (e.g. "Python", "Azure DevOps", "Kubernetes", "PRINCE2").
   - required_skills = must-have / mandatory.  preferred_skills = nice-to-have / bonus.
   - Classification rules:
     - technical = programming languages, frameworks, libraries, cloud platforms, databases, architecture styles...
     - methodologies = Agile, Scrum, SAFe, Kanban, PRINCE2, ITIL, PMI, Lean, Six Sigma, Design Thinking...
     - tools = specific platforms, ERP, CI/CD tools, monitoring, project management tools, IDEs...
   - Deduplicate aggressively: the same skill must appear in only one place (required or preferred, and only one category).
   - If a skill is mentioned multiple times with different wordings, keep the clearest canonical form once.
   - Do not put soft skills or generic adjectives here.

3. LANGUAGES - careful identification
   - Only extract human (spoken/written) languages and programming languages that are explicitly required or preferred.
   - For each language: type "spoken" or "programming"; level only if mentioned (Native, Fluent, C1, B2...); required=true only if the JD makes it mandatory.
   - Quote the exact short evidence phrase. Never invent a language requirement from generic phrases.

4. GENERAL
   - experience.min_years = the lowest number clearly stated. preferred_years if a range is given.
   - Never invent. Empty lists / "Not mentioned" are perfectly fine and preferred over guesses.
   - Keep lists short and high-signal.

Job Description:
{{job_text}}
"""


def parse_job_v2(job_text: str, api_key: str, force_refresh: bool = False) -> Dict[str, Any]:
    """ONE Gemini call -> structured job JSON (V2 prompt, V3 gateway).

    Returns a V2-shaped job dict (with ``_api_error`` flag). Raises
    :class:`GatewayError` only when the provider itself fails.
    """
    job_hash = hashlib.sha256(job_text.strip().encode("utf-8")).hexdigest()
    if not force_refresh and job_hash in _JD_CACHE:
        return _JD_CACHE[job_hash]

    prompt = _JD_PROMPT.replace("{job_text}", job_text[:25000])

    # ------------------------------------------------------------------
    # PROMPT-INJECTION GUARD (root-cause fix for the "every job = 100%"
    # bug).  The template used to render as "{\njob_text}", so the
    # ``.replace`` above silently matched NOTHING and Gemini was asked to
    # parse a job description that was never actually included - it then
    # echoed/hallucinated requirements and every JD scored as a perfect
    # fit with no skill gaps.  Fail loudly if the text ever fails to be
    # injected again instead of silently analysing nothing.
    # ------------------------------------------------------------------
    if job_text[:25000].strip() and job_text[:25000] not in prompt:
        raise GatewayError(
            "Internal prompt error: the job description was not injected into "
            "the analysis prompt. Please report this issue."
        )

    def _default(error: bool = False) -> Dict[str, Any]:
        return {
            "job_title": "", "company_name": "", "location": "", "country": "",
            "city": "", "address": "", "company_website": "", "company_linkedin": "",
            "company_phone": "", "industry": "", "seniority_level": "",
            "recruiter_contact": {"name": "", "position": "", "email": "", "linkedin_url": "", "phone": ""},
            "visa_sponsorship": {}, "work_authorization": {},
            "required_skills": {"technical": [], "methodologies": [], "tools": []},
            "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
            "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
            "education": {"min_degree": "", "preferred_fields": []},
            "languages": [], "certifications": [], "responsibilities": [], "keywords": [],
            "location_requirements": {}, "_api_error": error,
        }

    response = _call_gemini(prompt, api_key, json_mode=True)
    if not response:
        raise GatewayError("Gemini API Connection Failed.")

    def _list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    try:
        parsed = json.loads(_clean_json_response(response))
        if not isinstance(parsed, dict):
            raise ValueError("JD parse returned non-object JSON")
        result = _default(False)
        result.update({
            "job_title": str(parsed.get("job_title") or "").strip(),
            "company_name": str(parsed.get("company_name") or "").strip(),
            "location": str(parsed.get("location") or "").strip(),
            "country": str(parsed.get("country") or "").strip(),
            "city": str(parsed.get("city") or "").strip(),
            "address": str(parsed.get("address") or "").strip(),
            "company_website": str(parsed.get("company_website") or "").strip(),
            "company_linkedin": str(parsed.get("company_linkedin") or "").strip(),
            "company_phone": str(parsed.get("company_phone") or "").strip(),
            "industry": str(parsed.get("industry") or "").strip(),
            "seniority_level": str(parsed.get("seniority_level") or "").strip(),
        })
        # V2 self-heal: some models return the company under "company" (the
        # 0006 migration + _find_or_create_company also accept this alias).
        if not result["company_name"]:
            for _alias in ("company", "companyName", "employer", "organization"):
                _v = parsed.get(_alias)
                if isinstance(_v, dict):
                    _v = _v.get("name", "")
                if str(_v or "").strip():
                    result["company_name"] = str(_v).strip()
                    break
        rc = parsed.get("recruiter_contact") or parsed.get("recruiter") or {}
        if isinstance(rc, dict):
            result["recruiter_contact"] = {
                "name": str(rc.get("name") or "").strip(),
                "position": str(rc.get("position") or rc.get("title") or "").strip(),
                "email": str(rc.get("email") or "").strip(),
                "linkedin_url": str(rc.get("linkedin_url") or rc.get("linkedin") or "").strip(),
                "phone": str(rc.get("phone") or rc.get("phone_number") or rc.get("tel") or "").strip(),
            }
        # Deterministic fallback: the AI schema only fires when Gemini names
        # an individual contact. When the JD states one inline (name + email
        # on nearby lines), extract it verbatim so "RH defined in JD" never
        # silently becomes "no recruiter". Generic inboxes are never a person.
        if not any(result["recruiter_contact"].values()):
            fb = extract_recruiter_from_jd_text(job_text)
            if any(fb.values()):
                result["recruiter_contact"] = fb
        for key in ("visa_sponsorship", "work_authorization", "location_requirements"):
            value = parsed.get(key, {})
            if isinstance(value, dict):
                result[key] = value
        req = parsed.get("required_skills") or {}
        pref = parsed.get("preferred_skills") or {}
        if isinstance(req, dict):
            result["required_skills"] = {
                "technical": [str(x).strip() for x in _list(req.get("technical")) if str(x).strip()],
                "methodologies": [str(x).strip() for x in _list(req.get("methodologies")) if str(x).strip()],
                "tools": [str(x).strip() for x in _list(req.get("tools")) if str(x).strip()],
            }
        if isinstance(pref, dict):
            result["preferred_skills"] = {
                "technical": [str(x).strip() for x in _list(pref.get("technical")) if str(x).strip()],
                "methodologies": [str(x).strip() for x in _list(pref.get("methodologies")) if str(x).strip()],
                "tools": [str(x).strip() for x in _list(pref.get("tools")) if str(x).strip()],
            }
        exp = parsed.get("experience") or {}
        if isinstance(exp, dict):
            result["experience"] = {
                "min_years": int(exp.get("min_years") or 0),
                "preferred_years": int(exp.get("preferred_years") or 0),
                "level": str(exp.get("level") or "").strip(),
            }
        edu = parsed.get("education") or {}
        if isinstance(edu, dict):
            result["education"] = {
                "min_degree": str(edu.get("min_degree") or "").strip(),
                "preferred_fields": [str(x).strip() for x in _list(edu.get("preferred_fields")) if str(x).strip()],
            }
        result["certifications"] = [str(x).strip() for x in _list(parsed.get("certifications")) if str(x).strip()]
        result["responsibilities"] = [str(x).strip() for x in _list(parsed.get("responsibilities")) if str(x).strip()]
        result["keywords"] = [str(x).strip() for x in _list(parsed.get("keywords")) if str(x).strip()]
        result["languages"] = []
        for lang in _list(parsed.get("languages")):
            if isinstance(lang, dict):
                result["languages"].append({
                    "language": str(lang.get("language") or "").strip(),
                    "level": str(lang.get("level") or "").strip(),
                    "required": bool(lang.get("required", True)),
                })
            elif isinstance(lang, str) and lang.strip():
                result["languages"].append({"language": lang.strip(), "level": "", "required": True})

        # ------------------------------------------------------------------
        # DEGENERATE-PARSE GATE (critical fix for the fake 100% bug).
        #
        # Some models answer the parse prompt by echoing the empty schema
        # template (valid JSON, all fields empty).  Treating that as a
        # successful parse used to feed the engine empty requirements, and
        # every scoring function then returned 100% with no missing skills.
        # If NOTHING meaningful was extracted, flag the parse as failed so
        # the engine scores 0% and the UI can ask for a retry.
        # ------------------------------------------------------------------
        exp_ok = bool(result["experience"]["min_years"] or result["experience"]["preferred_years"])
        edu_ok = bool(result["education"]["min_degree"] or result["education"]["preferred_fields"])
        req_ok = bool(
            result["required_skills"]["technical"]
            or result["required_skills"]["methodologies"]
            or result["required_skills"]["tools"]
            or result["certifications"]
            or result["languages"]
        )
        identity_ok = bool(result["job_title"] or result["industry"] or result["keywords"])
        if not (req_ok or exp_ok or edu_ok or identity_ok):
            result["_api_error"] = True
            result["_parse_reason"] = "degenerate_parse: no requirements extracted"

        _JD_CACHE[job_hash] = result
        return result
    except (ValueError, json.JSONDecodeError):
        default = _default(True)
        _JD_CACHE[job_hash] = default
        return default


# =============================================================================
# 6. RECRUITER CONTACT EXTRACTION (deterministic JD-text fallback)
# =============================================================================
# The Gemini schema only yields recruiter_contact when the model names an
# individual. This fallback scans the RAW JD text verbatim (no invention):
# an email near a person name (+ optional position/LinkedIn) becomes the
# contact. Generic inboxes (info@/careers@/...) are never a person.
_RECRUITER_GENERIC_PREFIXES = (
    "info@", "contact@", "careers@", "jobs@", "hr@", "hello@",
    "recruitment@", "noreply@", "bewerbung@",
)
_RECRUITER_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_RECRUITER_URL_RE = re.compile(r"https?://[^\s)]+|(?:www\.)?linkedin\.com/in/[^\s)]+", re.IGNORECASE)
# International phone: optional + country code, optional area group, then
# 2-4 digit prefix and a 4-8 digit run (separators/spaces optional). Best
# effort, deterministic; only used inside the recruiter contact window.
_RECRUITER_PHONE_RE = re.compile(
    r"(\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}[\s.-]?\d{4,8}"
)
_RECRUITER_POSITION_HINTS = (
    "recruit", "talent acquisition", "talent-acquisition", "hiring manager",
    "hiring-manager", "hr ", "human resources", "people ", "staffing",
    "personalabteilung", "personalreferent", "recruteur",
    "talent manager", "sourcer", "headhunter",
)
# "Anna Mueller" / "Jean-Pierre Dupont" — 2+ capitalized words, no digits.
_RECRUITER_NAME_RE = re.compile(
    r"\b([A-ZÀ-Þ][a-zà-ÿ'’-]+(?:[ -][A-ZÀ-Þ][a-zà-ÿ'’-]+)+)\b"
)


def _recruiter_name_from_lines(lines: List[str]) -> str:
    # Prefer lines that look like a contact label ("Contact:", "Recruiter:",
    # "Hiring Manager:", "Ansprechpartner:", ...) so a job TITLE line
    # ("Senior Data Engineer - Acme") never wins over the real person name.
    ordered = sorted(
        lines,
        key=lambda ln: 0 if re.search(
            r"contact|recruit|hiring|talent|hr\b|human resources|ansprechpartner|chargé",
            ln, re.IGNORECASE) else 1,
    )
    for line in ordered:
        m = _RECRUITER_NAME_RE.search(line)
        if not m:
            continue
        name = m.group(1).strip()
        low = name.lower()
        # Skip company-ish / section-ish matches, keep person names only.
        if any(w in low for w in ("gmbh", " ag", "inc", "ltd", "s.a", "company",
                                  "department", "team", "job description",
                                  "requirements", "responsibilities", "apply",
                                  "data engineer", "data scientist", "software",
                                  "nurse", "engineer", "manager", "developer",
                                  "analyst", "senior", "junior")):
            continue
        if len(name) <= 40:
            return name
    return ""


def extract_recruiter_from_jd_text(job_text: str) -> Dict[str, str]:
    """Best-effort verbatim recruiter extraction from the raw JD text.

    Returns {name, position, email, linkedin_url, phone}; all "" when the JD names
    no individual contact. Deterministic: same text -> same contact.
    """
    empty = {"name": "", "position": "", "email": "", "linkedin_url": "", "phone": ""}
    if not job_text or not job_text.strip():
        return empty
    lines = [ln.strip() for ln in str(job_text).splitlines()]
    # Collect individual (non-generic) emails with their line index.
    hits: List[Tuple[int, str]] = []
    for i, ln in enumerate(lines):
        for em in _RECRUITER_EMAIL_RE.findall(ln):
            low = em.lower()
            if any(low.startswith(p) for p in _RECRUITER_GENERIC_PREFIXES):
                continue
            # Skip emails whose local part is clearly a role, not a person.
            local = low.split("@")[0]
            if any(w in local for w in ("info", "contact", "career", "jobs",
                                        "bewerbung", "noreply", "hello")):
                continue
            hits.append((i, em.strip()))
    if not hits:
        return empty
    # Prefer the email whose surroundings mention recruiting/hiring.
    best_idx, best_email = hits[0]
    for i, em in hits:
        window = " ".join(lines[max(0, i - 3): i + 4]).lower()
        if any(h in window for h in _RECRUITER_POSITION_HINTS):
            best_idx, best_email = i, em
            break
    window_lines = lines[max(0, best_idx - 4): best_idx + 5]
    name = _recruiter_name_from_lines(window_lines)
    position = ""
    for ln in window_lines:
        low = ln.lower()
        if any(h in low for h in _RECRUITER_POSITION_HINTS):
            position = ln.strip()[:120]
            break
    linkedin = ""
    phone = ""
    for ln in window_lines:
        m = _RECRUITER_URL_RE.search(ln)
        if m and "linkedin" in m.group(0).lower():
            linkedin = m.group(0).strip()
            break
    # Phone: prefer a number on the SAME line as the email or name, else the
    # phone-only line inside the contact window.
    for ln in window_lines:
        pm = _RECRUITER_PHONE_RE.search(ln)
        if not pm:
            continue
        phone_candidate = pm.group(0).strip()
        if phone_candidate and any(c.isdigit() for c in phone_candidate):
            phone = phone_candidate
            break
    # A contact without a person name is not an individual recruiter.
    if not name:
        return empty
    return {"name": name, "position": position,
            "email": best_email, "linkedin_url": linkedin, "phone": phone}


# ==============================================================================
# 7. DETERMINISTIC ATS ENGINE + THRESHOLD GATING (V2 verbatim)
# ==============================================================================

_NOISE_WORDS = ("credentials", "certificate", "certification", "experience", "knowledge", "skills", "skill")


def compute_ats_engine(
    candidate: Dict[str, Any],
    job: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """V2 ``compute_ats_engine`` - identical formula, labels and filter.

    CRITICAL FIX: When job parsing fails (``_api_error=True``), requirements
    are empty and the legacy scoring functions return 100% for every category.
    This makes a failed parse look like a perfect match.  We detect that case
    and force a 0% score with a clear ``parse_failed`` flag so the UI can
    show an actionable error instead of a fake 100%.
    """
    weights = weights or DEFAULT_WEIGHTS

    # --- Detect a failed job parse (empty requirements = fake 100%) ---
    parse_failed = bool(job.get("_api_error"))

    # Also detect when parsing "succeeds" but returns NO requirements at all.
    # This happens when Gemini returns valid JSON but fails to extract any
    # meaningful requirements from the job description.  Without this check,
    # every scoring function returns 100% and the overall score is a fake 100%.
    if not parse_failed:
        has_requirements = any([
            job.get("required_skills", {}).get("technical"),
            job.get("required_skills", {}).get("methodologies"),
            job.get("required_skills", {}).get("tools"),
            job.get("certifications"),
            job.get("languages"),
            job.get("experience", {}).get("min_years", 0) > 0,
            job.get("experience", {}).get("preferred_years", 0) > 0,
            job.get("education", {}).get("min_degree"),
            job.get("education", {}).get("preferred_fields"),
            job.get("industry"),
        ])
        if not has_requirements:
            parse_failed = True

    all_evidence: List[Dict[str, Any]] = []
    missing: List[str] = []
    strengths: List[str] = []

    def _cat(required: List[str], category: str) -> float:
        score, ev, miss = _score_list_match(required, candidate, category)
        all_evidence.extend(ev)
        missing.extend(miss)
        return score

    if parse_failed:
        # Never reward a failed parse: force every category to 0.
        tech_score = meth_score = tools_score = cert_score = 0.0
        lang_score = exp_score = edu_score = ind_score = 0.0
        lang_ev, lang_miss = [], []
    else:
        tech_score = _cat(job.get("required_skills", {}).get("technical") or [], "technical")
        meth_score = _cat(job.get("required_skills", {}).get("methodologies") or [], "methodologies")
        tools_score = _cat(job.get("required_skills", {}).get("tools") or [], "tools")
        cert_score = _cat(job.get("certifications") or [], "certifications")

        lang_score, lang_ev, lang_miss = _score_languages(candidate, job)
        all_evidence.extend(lang_ev)
        missing.extend(lang_miss)

        exp_score = _score_experience(candidate, job)
        edu_score = _score_education(candidate, job)
        ind_score = _score_industry(candidate, job)

    for cat in ("technical", "methodologies", "tools"):
        for item in job.get("preferred_skills", {}).get(cat) or []:
            if _evidence_level(item, candidate, cat) >= 3:
                strengths.append(item)

    for ev in all_evidence:
        if ev["level"] >= 4:
            strengths.append(ev["item"])

    # ---------- Coherence filter (V2: never same item on both sides) ----------
    def _normalize(text: str) -> str:
        t = text.lower().strip()
        for noise in _NOISE_WORDS:
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
    overall = round(sum(sub_scores.get(key, 0.0) * w for key, w in weights.items()), 1)

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
        "parse_failed": parse_failed,
        "sub_scores": sub_scores,
        "weights": weights,
        "gap_analysis": {"missing": missing, "strengths": strengths},
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
# 6b. THRESHOLD + POSSIBLE RESPONSES (V2 analyzer, revised - CHG-017)
# ==============================================================================

# The FOUR threshold stages - revised per user approval (Spec B, CHG-017):
#   1. score < 70        -> hard reject (strongly recommend moving to another offer).
#   2. 70 <= score < 80  -> soft reject (not yet suitable; strengthen, re-analyse).
#   3. 80 <= score < 90  -> manual approval gate (user decides).
#   4. score >= 90       -> strong match: proceed to the post-ATS assessment.
# These boundaries now align with the engine decision labels (>=90 Excellent /
# >=80 Strong / >=70 Good), so the verdict and the displayed label never
# contradict each other.
# Every numeric band response carries the SAME shape:
#   {band, title, message, next_step, proceed}.
THRESHOLD_BANDS: List[Dict[str, Any]] = [
    {
        "band": "hard_reject",
        "min": float("-inf"),
        "max_exclusive": 70.0,
        "title": "Hard rejection - this offer does not fit your profile",
        "message": (
            "This job does not fit your current profile. I strongly recommend moving to other "
            "offers that are more aligned with your experience and skills. "
            "Tip: look for roles closer to your strongest skills and experience level."
        ),
        "next_step": "Move to another job offer closer to your strongest skills and experience level.",
        "proceed": False,
    },
    {
        "band": "soft_reject",
        "min": 70.0,
        "max_exclusive": 80.0,
        "title": "Soft rejection - strengthen your profile first",
        "message": (
            "This job is not yet suitable for your current profile. AIROS recommendation: "
            "strengthen the missing skills shown above - consider targeted training or "
            "certifications - gain additional experience in the required areas. "
            "Once your profile is stronger, you can re-analyse this offer."
        ),
        "next_step": "Strengthen the missing skills shown above, then re-analyse this offer later.",
        "proceed": False,
    },
    {
        "band": "manual",
        "min": 80.0,
        "max_exclusive": 90.0,
        "title": "Borderline match (80-89%) - your call",
        "message": (
            "Borderline match (80-89%). This role is close to your profile but not a clear strong "
            "match. Would you like to proceed and save it for further tracking?"
        ),
        "next_step": "Decide: approve and continue to the post-ATS assessment, or move to another offer.",
        "proceed": True,
    },
    {
        "band": "proceed",
        "min": 90.0,
        "max_exclusive": float("inf"),
        "title": "Strong match - proceed",
        "message": (
            "Strong match (>= 90%). This role is well aligned with your profile. "
            "You can now review the company details and save the job."
        ),
        "next_step": "Proceed to the post-ATS assessment process (save the job, prepare your application).",
        "proceed": True,
    },
]

# Non-numeric possible response (still deterministic):
#   - "blockers": any hard bottleneck forces the NO path regardless of the
#     score; the response lists EVERY blocker explicitly so the user sees
#     exactly which bottleneck(s) blocked the offer.
#   - invalid score (None / NaN / +/-inf / non-numeric): fail-safe NO path
#     with an explicit "unreliable score" message - a scoring failure can
#     never silently become a "proceed".
_BLOCKERS_TITLE = "Hard blockers detected - this job is not recommended"


def _band_response(band: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "band": band["band"],
        "title": band["title"],
        "message": band["message"],
        "next_step": band["next_step"],
        "proceed": band["proceed"],
    }


def _blockers_response(hard_blockers: List[str]) -> Dict[str, Any]:
    blockers_txt = "; ".join(hard_blockers)
    return {
        "band": "blockers",
        "title": _BLOCKERS_TITLE,
        "message": (
            "Hard blockers detected - this job is not recommended for your current profile. "
            f"Blockers: {blockers_txt}."
        ),
        "next_step": "Address the hard blockers (update your profile) or move to another offer.",
        "proceed": False,
    }


_INVALID_SCORE_RESPONSE: Dict[str, Any] = {
    "band": "hard_reject",
    "title": "Analysis did not produce a reliable score",
    "message": (
        "This job could not be scored reliably (the job parse failed or returned an invalid "
        "result). AIROS will not recommend this offer - the result is a safe NO, not a guess."
    ),
    "next_step": "Re-analyse the offer, or move to another offer closer to your profile.",
    "proceed": False,
}


def classify_threshold(
    score: Optional[float],
    hard_blockers: List[str],
) -> Dict[str, Any]:
    """ATS analyzer gating (revised Spec B, CHG-017) - FOUR stages:

    - <70          -> hard reject: strongly recommend moving to another offer.
    - 70-79        -> soft reject: not yet suitable; strengthen, re-analyse later.
    - 80-89        -> manual approval gate (user decides).
    - >=90         -> strong match: proceed to the post-ATS assessment process.

    Possible responses (CHG-017) - every verdict is deterministic and carries
    the SAME shape {band, title, message, next_step, proceed}:
    - hard_reject / soft_reject / manual / proceed: the numeric band above.
    - blockers: any hard blocker forces the NO path regardless of the score and
      the message lists EVERY blocker explicitly.
    - invalid score (None, NaN, +/-inf, non-numeric): fail-safe NO path
      ("analysis unreliable") so a scoring failure can never become "proceed".
    """
    if hard_blockers:
        return _blockers_response(hard_blockers)

    # Fail-safe input guard: a non-finite / missing / non-numeric score means
    # "no reliable score" -> the explicit NO path, never a silent wrong band.
    if (
        score is None
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        return dict(_INVALID_SCORE_RESPONSE)

    for band in THRESHOLD_BANDS:
        if band["min"] <= score < band["max_exclusive"]:
            return _band_response(band)

    # Unreachable deterministic fallback (keeps the function total).
    return dict(_INVALID_SCORE_RESPONSE)


def calculate_ats_gap(
    profile: Dict[str, Any],
    job_text: str,
    api_key: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Public entry point (V2 ``calculate_ats_gap``): candidate + ONE Gemini
    call for the job, then the deterministic engine + hard blockers + verdict."""
    candidate = build_candidate_json(profile or {})
    job = parse_job_v2(job_text, api_key, force_refresh=force_refresh)
    result = compute_ats_engine(candidate, job)

    blockers, explanations = check_hard_blockers(candidate, job, job_text)
    result["hard_blockers"] = blockers
    result["blocker_explanations"] = explanations
    result["ats_score"] = int(round(result["overall_ats"]))
    result["hits"] = result["gap_analysis"]["strengths"]
    result["gaps"] = result["gap_analysis"]["missing"]
    result["parsed_job"] = job
    result["parsed_cv"] = candidate
    result["verdict"] = classify_threshold(result["overall_ats"], blockers)

    # Clear positive visa indication (user verdict 2): when the company
    # clearly supports visa sponsorship, say so explicitly - even if negative
    # wording like "EU citizens only" also appears (which check_hard_blockers
    # then deliberately does NOT treat as a blocker).  The user must SEE both
    # the restrictive phrase and the positive sponsorship phrase.
    _, negative_phrase, positive_phrase = _visa_signals(job_text)
    if positive_phrase:
        restrictive = negative_phrase or '"right to work"-style wording'
        result["visa_note"] = (
            f'This job contains restrictive wording ("{restrictive}") for non-EU candidates, '
            f'but the company clearly indicates visa/relocation support ("{positive_phrase}"). '
            "That restriction therefore does NOT block you - you can still apply."
        )
    return result