"""AIROS V3 - Deterministic ATS engine + Job Analyzer route tests (DEC-006).

Verifies the V2-ported algorithm offline:
- deterministic weights/labels/coherence filter (same input -> same number),
- hard blockers (visa, local language, fast start, experience gap),
- threshold gating (hard/soft/manual/proceed), candidate builder from a V3 row,
- ONE-call Gemini job parse (mocked at the gateway boundary),
- POST /api/ats/analyze: auth guard, profile guard, RLS token forwarding,
  Gemini-key guard, error mapping.
"""

from __future__ import annotations

import json

import pytest

import httpx

from ai import ats
from ai.ats import (
    GatewayError,
    build_candidate_json,
    calculate_ats_gap,
    check_hard_blockers,
    classify_threshold,
    compute_ats_engine,
    extract_recruiter_from_jd_text,
    parse_job_v2,
)
from tests.conftest import mint_token

# A plausible V3 profiles row (identity/education/experience/skills/languages/...).
V3_PROFILE_ROW = {
    "identity": {
        "first_name": "Aymen", "last_name": "Dr",
        "city": "Tunis", "nationality": "Tunisian",
    },
    "education": [
        {"degree": "Master of Science", "field_of_study": "Information Systems",
         "institution": "UT", "start_year": "2019", "end_year": "2023"}
    ],
    "experience": [
        {"company": "Acme", "title": "Engineer", "start_date": "01.2016",
         "end_date": "Present", "currently_working": True,
         "description": "Built Python services with Docker and PostgreSQL."},
        {"company": "Beta", "title": "DevOps", "start_date": "03.2014",
         "end_date": "12.2015", "description": "CI/CD pipelines."},
    ],
    "skills": {
        "TECHNICAL": ["Python", "Docker", "PostgreSQL"],
        "MANAGEMENT": ["Agile"],
        "CORE": ["Communication"],
        "sections": [{"section_title": "Tools & Technologies", "items": ["Python", "Kubernetes"]}],
    },
    "languages": [{"language": "French", "level": "C2"}, {"language": "English", "level": "C1"}],
    "certifications": [{"name": "PMP", "issuer": "PMI", "year": "2020"}],
}


def _job(overrides=None) -> dict:
    job = {
        "job_title": "Senior Python Engineer",
        "company_name": "Siemens AG",
        "industry": "",
        "experience": {"min_years": 3, "preferred_years": 5, "level": "Senior"},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [{"language": "English", "level": "C1", "required": True}],
        "required_skills": {
            "technical": ["Python", "Docker", "Kubernetes", "Go"],
            "methodologies": ["Agile"],
            "tools": [],
        },
        "preferred_skills": {"technical": ["FastAPI"], "methodologies": [], "tools": []},
        "certifications": [],
    }
    if overrides:
        job.update(overrides)
    return job


# ---------------------------------------------------------------------------
# Candidate builder (V3 row -> engine candidate)
# ---------------------------------------------------------------------------

def test_build_candidate_from_v3_row():
    cand = build_candidate_json(V3_PROFILE_ROW)
    assert cand["total_experience_years"] >= 10  # 2014..2026 roles sum
    assert "Python" in cand["skills"]["technical"]
    assert "Kubernetes" in cand["skills"]["technical"]  # sections merged in
    assert cand["skills"]["methodologies"] == ["Agile"]
    assert cand["location"] == "Tunis"
    assert cand["nationality"] == "Tunisian"
    assert {"language": "French", "level": "C2"} in cand["languages"]
    assert "Aymen" not in cand  # no identity bleed into engine keys


def test_build_candidate_empty_profile_is_safe():
    cand = build_candidate_json({})
    assert cand["total_experience_years"] == 0
    assert cand["skills"]["technical"] == []


# ---------------------------------------------------------------------------
# Deterministic engine (V2 weights formula + labels)
# ---------------------------------------------------------------------------

def test_engine_score_matches_v2_weighted_formula():
    cand = build_candidate_json(V3_PROFILE_ROW)
    res = compute_ats_engine(cand, _job())
    sub = res["sub_scores"]
    # technical: Python+Docker+Kubernetes matched, Go missing -> 3/4 = 75
    assert sub["technical_skills"] == 75.0
    # methodologies: Agile exact -> 100
    assert sub["methodologies"] == 100.0
    # languages: English C1 -> 100
    assert sub["languages"] == 100.0
    # experience: cand_years>=pref(5) -> 100
    assert sub["experience"] == 100.0
    # with no min_degree/no fields and empty industry -> both 100
    assert sub["education"] == 100.0
    assert sub["industry"] == 100.0
    expected = round(
        75.0 * 0.30 + 100.0 * 0.25 + 100.0 * 0.10 + 100.0 * 0.10
        + 100.0 * 0.10 + 100.0 * 0.05 + 100.0 * 0.05 + 100.0 * 0.05,
        1,
    )
    assert res["overall_ats"] == expected
    assert "Go" in res["gap_analysis"]["missing"]
    assert "Python" in res["gap_analysis"]["strengths"]


def test_engine_education_scoring():
    cand = build_candidate_json(V3_PROFILE_ROW)
    # Master(4) >= Bachelor(3) requirement -> degree 100; wrong field -> 40
    res = compute_ats_engine(cand, _job({"education": {"min_degree": "Bachelor", "preferred_fields": ["computer science"]}}))
    assert res["sub_scores"]["education"] == 82.0  # 100*0.7 + 40*0.3
    # Above requirement -> 100 even without the preferred field
    res2 = compute_ats_engine(cand, _job({"education": {"min_degree": "Master", "preferred_fields": ["history"]}}))
    assert res2["sub_scores"]["education"] == 82.0
    # Far below requirement -> degree penalised (V2: (best/required)*80 = 64);
    # with empty preferred_fields the field component is 100 -> 64*0.7 + 100*0.3
    res3 = compute_ats_engine(cand, _job({"education": {"min_degree": "PhD", "preferred_fields": []}}))
    assert res3["sub_scores"]["education"] == 74.8


def test_engine_decision_labels():
    low = compute_ats_engine(build_candidate_json({}), _job())
    assert low["decision"] == "Weak Match"
    assert low["overall_ats"] < 60


def test_engine_coherence_filter_removes_dupes():
    res = compute_ats_engine(build_candidate_json(V3_PROFILE_ROW), _job())
    items = res["gap_analysis"]["missing"]
    assert items == sorted(set(items))
    assert "Python" not in items  # strong hit, never also a gap


def test_engine_parse_failure_returns_zero_not_100():
    """CRITICAL: When job parsing fails (API error / bad JSON), the default
    structure has empty requirements.  The legacy scoring functions return
    100% for empty requirements, which would make a failed parse look like
    a perfect match.  The fix forces 0% and sets ``parse_failed=True``.
    """
    cand = build_candidate_json(V3_PROFILE_ROW)

    # Simulate a failed parse: _api_error=True with empty requirements
    failed_job = {
        "job_title": "", "company_name": "", "location": "", "country": "",
        "city": "", "address": "", "company_website": "", "company_linkedin": "",
        "company_phone": "", "industry": "", "seniority_level": "",
        "visa_sponsorship": {}, "work_authorization": {},
        "required_skills": {"technical": [], "methodologies": [], "tools": []},
        "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [], "certifications": [], "responsibilities": [], "keywords": [],
        "location_requirements": {}, "_api_error": True,
    }
    res = compute_ats_engine(cand, failed_job)
    assert res["parse_failed"] is True
    assert res["overall_ats"] == 0.0
    assert res["decision"] == "Weak Match"


def test_engine_empty_requirements_returns_zero_not_100():
    """CRITICAL: When parsing 'succeeds' but returns NO requirements at all,
    the score must NOT be 100%.  This detects Gemini returning valid JSON
    but failing to extract any meaningful requirements from the job description.
    """
    cand = build_candidate_json(V3_PROFILE_ROW)

    # Simulate parsing that returned valid JSON but no requirements
    empty_job = {
        "job_title": "Some Role", "company_name": "Some Corp", "location": "",
        "country": "", "city": "", "address": "", "company_website": "",
        "company_linkedin": "", "company_phone": "", "industry": "",
        "seniority_level": "", "visa_sponsorship": {}, "work_authorization": {},
        "required_skills": {"technical": [], "methodologies": [], "tools": []},
        "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [], "certifications": [], "responsibilities": [], "keywords": [],
        "location_requirements": {}, "_api_error": False,
    }
    res = compute_ats_engine(cand, empty_job)
    assert res["parse_failed"] is True
    assert res["overall_ats"] == 0.0
    assert res["decision"] == "Weak Match"


# ---------------------------------------------------------------------------
# Hard blockers (V2 deterministic)
# ---------------------------------------------------------------------------

def test_blocker_visa_no_sponsorship_non_eu():
    cand = build_candidate_json(V3_PROFILE_ROW)  # Tunisian
    blockers, _ = check_hard_blockers(
        cand, _job(),
        "Senior role. Must already have the right to work. EU citizens only.",
    )
    assert "No Visa Sponsorship" in blockers


def test_blocker_visa_sponsorship_positive_clears():
    cand = build_candidate_json({})
    blockers, _ = check_hard_blockers(
        cand, _job(),
        "We offer full visa sponsorship and relocation support.",
    )
    assert "No Visa Sponsorship" not in blockers


def test_blocker_local_language_missing():
    cand = build_candidate_json(V3_PROFILE_ROW)  # no German
    job = _job({"languages": [{"language": "German", "level": "B2", "required": True}]})
    blockers, _ = check_hard_blockers(cand, job, "Must speak German.")
    assert blockers == ["Local Language: German"]


def test_blocker_experience_gap():
    # candidate with ~0 years vs required 5 -> gap (cand < 5*0.7=3.5)
    cand = build_candidate_json({"identity": {}, "experience": []})
    blockers, _ = check_hard_blockers(
        cand, _job({"experience": {"min_years": 5, "preferred_years": 8, "level": ""}}),
        "Requires 5+ years.",
    )
    assert "Major Experience Gap" in blockers


def test_blocker_api_failure_short_circuits():
    job = dict(_job(), _api_error=True)
    blockers, _ = check_hard_blockers(build_candidate_json({}), job, "")
    assert blockers == ["API Failure"]


# ---------------------------------------------------------------------------
# User verdict revisions (4-stage thresholds + hard blockers, V2 alignment)
# ---------------------------------------------------------------------------

def test_threshold_four_stages_wording():
    """The FOUR threshold stages exist with the decisive analyzer wording."""
    v = classify_threshold(60, [])
    assert v["band"] == "hard_reject" and v["proceed"] is False
    assert "strongly recommend moving to other offers" in v["message"]
    assert "Tip:" in v["message"]

    v = classify_threshold(75, [])
    assert v["band"] == "soft_reject" and v["proceed"] is False
    assert "not yet suitable" in v["message"]
    assert "AIROS recommendation" in v["message"]
    assert "re-analyse this offer" in v["message"]

    v = classify_threshold(85, [])
    assert v["band"] == "manual" and v["proceed"] is True
    assert "Borderline match" in v["message"]
    assert "80-89" in v["message"]

    v = classify_threshold(92, [])
    assert v["band"] == "proceed" and v["proceed"] is True
    assert "Strong match" in v["message"]
    assert ">= 90" in v["message"]

    # Hard blockers reinforce the gate (V2 shows them on the gated card).
    v = classify_threshold(95, ["Local Language: German"])
    assert v["band"] == "blockers" and v["proceed"] is False


def test_threshold_revision_exhaustive_possible_responses():
    """CHG-017: every possible response has the SAME deterministic shape
    {band, title, message, next_step, proceed}."""
    for score in (10.0, 69.0, 70.0, 75.0, 79.0, 80.0, 89.0, 90.0, 100.0):
        v = classify_threshold(score, [])
        assert set(v) == {"band", "title", "message", "next_step", "proceed"}
    v = classify_threshold(95.0, ["No Visa Sponsorship", "Local Language: German"])
    assert set(v) == {"band", "title", "message", "next_step", "proceed"}
    assert v["band"] == "blockers"


def test_threshold_revision_blockers_listed_in_response():
    """CHG-017: the blockers response names EVERY hard bottleneck so the user
    can see exactly what blocked the offer."""
    v = classify_threshold(95.0, ["No Visa Sponsorship", "Local Language: German"])
    assert v["band"] == "blockers" and v["proceed"] is False
    assert "No Visa Sponsorship" in v["message"]
    assert "Local Language: German" in v["message"]


def test_threshold_revision_invalid_score_failsafe_no():
    """CHG-017: None/NaN/inf/non-numeric scores ALWAYS end on the fail-safe NO
    path with an explicit message - never a crash, never a silent 'proceed'."""
    for bad in (None, float("nan"), float("inf"), float("-inf"), True, {}, "88"):
        v = classify_threshold(bad, [])
        assert v["band"] == "hard_reject"
        assert v["proceed"] is False
        assert "reliab" in v["message"]


def test_threshold_revision_parse_failure_maps_to_no():
    """A parse failure (API error) yields a real numeric 0 -> hard_reject NO."""
    job = dict(_job(), _api_error=True)
    result = compute_ats_engine(build_candidate_json(V3_PROFILE_ROW), job)
    v = classify_threshold(result["overall_ats"], result["hard_blockers"])
    assert result["overall_ats"] == 0  # engine fails safe to zero
    assert v["band"] == "hard_reject" and v["proceed"] is False


def test_blocker_local_language_level_below_required():
    """User verdict 2: a local language present but BELOW the demanded level
    is still a hard blocker, with both levels shown to the user."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    # min_years 0 isolates the language-level blocker from the experience gap.
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, explanations = check_hard_blockers(cand, job, "German C1 required.")
    assert blockers == ["Local Language Level: German"]
    assert "C1" in explanations[0] and "B1" in explanations[0]


def test_blocker_local_language_level_sufficient():
    """Meeting the demanded level is not a blocker."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "C1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "B2", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(cand, job, "German B2 required.")
    assert blockers == []


def test_blocker_dutch_language_missing():
    """User verdict 1: Dutch (Dutch/Netherlands market) is a hard bottleneck
    when the required local language is absent from the profile."""
    cand = build_candidate_json(V3_PROFILE_ROW)  # no Dutch
    job = _job({
        "languages": [{"language": "Dutch", "level": "B2", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, explanations = check_hard_blockers(cand, job, "Must speak Dutch.")
    assert blockers == ["Local Language: Dutch"]
    assert "Dutch" in explanations[0]


def test_blocker_dutch_language_level_below_required():
    """User verdict 1: Dutch below the demanded level is also a hard
    bottleneck (like German), with both levels shown to the user."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "Nederlands", "level": "A2"}],
    })
    job = _job({
        "languages": [{"language": "Dutch", "level": "B2", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, explanations = check_hard_blockers(cand, job, "Dutch B2 required.")
    assert blockers == ["Local Language Level: Dutch"]
    assert "B2" in explanations[0] and "A2" in explanations[0]


def test_blocker_german_deutsch_synonym_not_false_blocked():
    """'Deutsch' and 'German' are the SAME language - a candidate fluent in
    Deutsch must NOT be hard-blocked by a job requiring German B2."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "Deutsch", "level": "C1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "B2", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(cand, job, "German B2 required.")
    assert blockers == []


def test_blocker_level_not_invented_from_parse():
    """USER REPORT (German C1): when the raw JD does NOT state a language
    level, a Gemini-parsed 'C1' must NEVER hard-block a B1 candidate."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    # job.languages claims C1 (simulated Gemini parse over-claim), but the RAW
    # job text only asks for "excellent German" - no explicit level anywhere.
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(cand, job, "The job requires excellent German skills.")
    assert "Local Language Level" not in blockers
    assert blockers == []


def test_blocker_level_still_fires_when_raw_text_states_it():
    """The level bottleneck still fires when the RAW JD text explicitly states
    the level - a C1-stated German requirement blocks a B1 candidate."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, explanations = check_hard_blockers(cand, job, "German C1 required.")
    assert "Local Language Level: German" in blockers
    assert "C1" in explanations[0] and "B1" in explanations[0]


def test_blocker_fluent_german_is_not_a_hard_cefr_level():
    """USER REPORT: 'fluent German' is NOT an explicit CEFR level - it must
    never create a hard C1 bottleneck on a B1 profile."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],  # parser over-claim
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(cand, job, "We require a fluent German speaker.")
    assert "Local Language Level" not in blockers
    assert blockers == []


def test_blocker_no_cross_sentence_contamination():
    """A level stated for ENGLISH in a different sentence must not become a
    German hard level requirement."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(
        cand, job,
        "Good German required. English must be at C1.",
    )
    assert "Local Language Level" not in blockers
    assert blockers == []


def test_blocker_nearest_level_wins_in_same_sentence():
    """'German at B2, English at C1' attributes B2 to German, not C1."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, explanations = check_hard_blockers(cand, job, "German at B2, English at C1.")
    assert "Local Language Level: German" in blockers
    assert "B2" in explanations[0] and "C1" not in explanations[0]


def test_blocker_level_evidence_quoted_in_explanation():
    """The explanation quotes the exact sentence so the user can verify WHY the
    level gate fired (no hidden magic)."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "German", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "German", "level": "C1", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    _, explanations = check_hard_blockers(cand, job, "German is required at a minimum of C1.")
    assert '"german is required at a minimum of c1"' in explanations[0]


def test_blocker_dutch_level_stated_in_dutch_raw_text():
    """'Nederlands op B2' in the raw JD is detected through the language alias
    and enforces the level gate on a Dutch-mapped profile."""
    cand = build_candidate_json({
        "identity": {},
        "languages": [{"language": "Dutch", "level": "B1"}],
    })
    job = _job({
        "languages": [{"language": "Nederlands", "level": "B2", "required": True}],
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
    })
    blockers, _ = check_hard_blockers(cand, job, "Wij zoeken iemand met Nederlands op B2-niveau.")
    assert "Local Language Level: Nederlands" in blockers


def test_blocker_visa_negative_wording_quoted_in_explanation():
    """The user sees exactly which negative phrase triggered the blocker."""
    cand = build_candidate_json(V3_PROFILE_ROW)  # Tunisian (non-EU hint)
    blockers, explanations = check_hard_blockers(
        cand, _job(),
        "Senior role. Must already have the right to work.",
    )
    assert blockers == ["No Visa Sponsorship"]
    assert "must already have the right to work" in explanations[0]


def test_visa_note_surfaces_clear_sponsorship(monkeypatch):
    """User verdict 2: when the company CLEARLY supports visa sponsorship,
    the user is told explicitly - and 'EU citizens only' wording does not
    block a non-EU candidate."""
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: json.dumps({
        "job_title": "DevOps Engineer",
        "required_skills": {"technical": ["Docker"], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [], "certifications": [],
    }))
    job_text = (
        "EU citizens only. However we offer full visa sponsorship, "
        "a blue card and relocation support."
    )
    cand = build_candidate_json(V3_PROFILE_ROW)  # Tunisian (non-EU)
    blockers, _ = check_hard_blockers(cand, _job(), job_text)
    assert blockers == []  # clear positive signal overrides the negative wording

    result = calculate_ats_gap(V3_PROFILE_ROW, job_text, "test-key")
    assert result["hard_blockers"] == []
    assert result["verdict"]["band"] != "blockers"
    assert result.get("visa_note")
    # the user must CLEARLY see BOTH the restrictive phrase and the support signal
    assert "eu citizens only" in result["visa_note"]
    assert "visa sponsorship" in result["visa_note"]


# ---------------------------------------------------------------------------
# Recruiter (RH) contact — parsed from the JD, never hidden "Anna..."
# ---------------------------------------------------------------------------

def test_recruiter_named_in_jd_is_extracted_verbatim():
    jd = (
        "Senior Data Engineer - Acme GmbH, Berlin\n"
        "Requirements: Python, Docker, 5y experience.\n"
        "Contact: Anna Mueller, Senior Talent Acquisition\n"
        "anna.mueller@acme.example\n"
        "https://linkedin.com/in/anna-mueller\n"
    )
    rc = extract_recruiter_from_jd_text(jd)
    assert rc["name"] == "Anna Mueller"
    assert rc["email"] == "anna.mueller@acme.example"
    assert "linkedin.com/in/anna-mueller" in rc["linkedin_url"]


def test_recruiter_generic_inbox_is_not_a_person():
    assert extract_recruiter_from_jd_text(
        "Nurse ICU, BLS required. Apply to jobs@clinic.example.") == {
        "name": "", "position": "", "email": "", "linkedin_url": "", "phone": ""}
    assert extract_recruiter_from_jd_text(
        "Contact our HR team at hr@company.example for details.") == {
        "name": "", "position": "", "email": "", "linkedin_url": "", "phone": ""}


def test_extract_recruiter_includes_phone_and_linkedin():
    jd = (
        "Contact: Anna Mueller, Senior Talent Acquisition\n"
        "anna.mueller@acme.example\n"
        "+49 170 1234567\n"
        "https://linkedin.com/in/anna-mueller\n"
    )
    rc = extract_recruiter_from_jd_text(jd)
    assert rc["name"] == "Anna Mueller"
    assert rc["email"] == "anna.mueller@acme.example"
    assert rc["phone"] == "+49 170 1234567"
    assert "linkedin.com/in/anna-mueller" in rc["linkedin_url"]


def test_parse_job_v2_carries_recruiter_contact(monkeypatch):
    def fake_gemini(prompt, api_key, json_mode=False, max_retries=2):
        assert "recruiter_contact" in prompt  # schema asks Gemini first
        return json.dumps({
            "job_title": "Senior Python Engineer",
            "company_name": "Siemens AG",
            "recruiter_contact": {
                "name": "Anna Mueller",
                "position": "Senior Talent Acquisition",
                "email": "anna.mueller@acme.example",
                "linkedin_url": "https://linkedin.com/in/anna-mueller",
            },
        })

    monkeypatch.setattr(ats, "_call_gemini", fake_gemini)
    job = parse_job_v2("Senior role, contact Anna Mueller anna.mueller@acme.example",
                       "k", force_refresh=True)
    assert job["recruiter_contact"]["name"] == "Anna Mueller"
    assert job["recruiter_contact"]["email"] == "anna.mueller@acme.example"


def test_parse_job_v2_falls_back_to_jd_text_when_gemini_omits_recruiter(monkeypatch):
    jd = ("Senior Data Engineer - Acme\n"
          "Contact: Anna Mueller, Senior Talent Acquisition\n"
          "anna.mueller@acme.example")
    monkeypatch.setattr(ats, "_call_gemini",
                        lambda *a, **k: json.dumps({"job_title": "Senior Data Engineer"}))
    job = parse_job_v2(jd, "k", force_refresh=True)
    assert job["recruiter_contact"]["name"] == "Anna Mueller"
    assert job["recruiter_contact"]["email"] == "anna.mueller@acme.example"


# ---------------------------------------------------------------------------
# Threshold gating (V2 analyzer bands)
# ---------------------------------------------------------------------------

def test_threshold_bands():
    # Stage 1: < 70 -> hard reject (decisive NO)
    assert classify_threshold(0.0, [])["band"] == "hard_reject"
    assert classify_threshold(69.99, [])["band"] == "hard_reject"
    assert classify_threshold(69.99, [])["proceed"] is False
    # Stage 2: 70 - 79 -> soft reject
    assert classify_threshold(70.0, [])["band"] == "soft_reject"
    assert classify_threshold(75.0, [])["band"] == "soft_reject"
    assert classify_threshold(79.99, [])["band"] == "soft_reject"
    assert classify_threshold(79.99, [])["proceed"] is False
    # Stage 3: 80 - 89 -> manual approval gate (user decides -> proceed True)
    assert classify_threshold(80.0, [])["band"] == "manual"
    assert classify_threshold(85.0, [])["band"] == "manual"
    assert classify_threshold(89.99, [])["band"] == "manual"
    assert classify_threshold(89.99, [])["proceed"] is True
    # Stage 4: >= 90 -> strong match / proceed
    assert classify_threshold(90.0, [])["band"] == "proceed"
    assert classify_threshold(95.0, [])["band"] == "proceed"
    assert classify_threshold(95.0, [])["proceed"] is True
    # hard blockers force the NO path regardless of score
    assert classify_threshold(90.0, ["No Visa Sponsorship"])["band"] == "blockers"
    assert classify_threshold(90.0, ["No Visa Sponsorship"])["proceed"] is False
    assert classify_threshold(30.0, [])["proceed"] is False


# ---------------------------------------------------------------------------
# ONE-call Gemini job parsing (gateway mocked)
# ---------------------------------------------------------------------------

def test_parse_job_v2_one_gemini_call(monkeypatch):
    calls = {}

    def fake_gemini(prompt, api_key, json_mode=False, max_retries=2):
        calls["api_key"] = api_key
        calls["json_mode"] = json_mode
        calls["prompt"] = prompt
        return json.dumps({
            "job_title": "Senior Python Engineer",
            "company_name": "Siemens AG",
            "industry": "software",
            "experience": {"min_years": 3, "preferred_years": 5},
            "education": {"min_degree": "Bachelor", "preferred_fields": ["computer science"]},
            "languages": [{"language": "German", "level": "B2", "required": True}],
            "required_skills": {"technical": ["Python "], "methodologies": [], "tools": []},
            "certifications": ["PMP"],
            "visa_sponsorship": {"support": "No", "evidence": "EU citizens only"},
        })

    monkeypatch.setattr(ats, "_call_gemini", fake_gemini)
    job = parse_job_v2("Senior role...", "test-key")
    assert job["job_title"] == "Senior Python Engineer"
    assert job["company_name"] == "Siemens AG"
    assert job["required_skills"]["technical"] == ["Python"]
    assert job["languages"][0]["language"] == "German"
    assert job["visa_sponsorship"]["support"] == "No"
    assert job["_api_error"] is False
    assert calls["json_mode"] is True
    assert "Job Description" in calls["prompt"]


def test_parse_job_v2_caches_by_hash(monkeypatch):
    calls = {"n": 0}

    def fake_gemini(prompt, api_key, json_mode=False, max_retries=2):
        calls["n"] += 1
        return '{"job_title": "X"}'

    monkeypatch.setattr(ats, "_call_gemini", fake_gemini)
    parse_job_v2("same job text", "k")
    parse_job_v2("same job text", "k")
    assert calls["n"] == 1  # cached -> ONE gemini call total


def test_parse_job_v2_gateway_failure_raises(monkeypatch):
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: None)
    with pytest.raises(GatewayError):
        parse_job_v2("job", "k")


def test_parse_job_v2_schema_echo_is_flagged_as_failed(monkeypatch):
    """CRITICAL (fake-100% root cause): when the model echoes the empty
    schema template (valid JSON, all fields empty), the parse must be
    flagged ``_api_error=True`` so the engine scores 0% instead of feeding
    empty requirements to scoring functions that return 100% for them."""
    schema_echo = json.dumps({
        "job_title": "", "company_name": "", "location": "", "country": "",
        "city": "", "industry": "", "seniority_level": "",
        "visa_sponsorship": {}, "work_authorization": {},
        "required_skills": {"technical": [], "methodologies": [], "tools": []},
        "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [], "certifications": [], "responsibilities": [], "keywords": [],
    })
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: schema_echo)
    job = parse_job_v2("schema echo job text", "k", force_refresh=True)
    assert job["_api_error"] is True
    assert job["_parse_reason"].startswith("degenerate_parse")


def test_parse_job_v2_vague_jd_with_title_is_not_degenerate(monkeypatch):
    """A JD with an identifiable title/industry but no requirements is a
    legitimate parse (the job simply has no extractable requirements) -
    it must NOT be flagged as a degenerate/failed parse."""
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: json.dumps({
        "job_title": "Team Member", "industry": "Hospitality",
        "required_skills": {"technical": [], "methodologies": [], "tools": []},
        "experience": {"min_years": 0, "preferred_years": 0, "level": ""},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [], "certifications": [],
    }))
    job = parse_job_v2("vague but titled job text", "k", force_refresh=True)
    assert job["_api_error"] is False
    assert job["job_title"] == "Team Member"

def test_prompt_includes_the_actual_job_text(monkeypatch):
    """ROOT-CAUSE regression (fake-100% bug): the JD template used to render
    as '{\\njob_text}', so ``.replace('{job_text}', ...)`` never matched and
    Gemini was asked to parse a job description that was never included -
    it then hallucinated/echoed requirements and every job scored ~100% with
    no skill gaps.  The real JD text MUST reach the Gemini prompt."""
    captured = {}

    def fake_gemini(prompt, api_key, json_mode=False, max_retries=2):
        captured["prompt"] = prompt
        return json.dumps({"job_title": "X"})

    monkeypatch.setattr(ats, "_call_gemini", fake_gemini)
    marker = "Kubernetes-cluster-SENTINEL-xyzzy"
    parse_job_v2(f"Senior role requiring {marker}", "k", force_refresh=True)
    assert marker in captured["prompt"]
    assert "{job_text}" not in captured["prompt"]  # placeholder fully substituted


def test_prompt_injection_guard_fails_loudly(monkeypatch):
    """If the template ever breaks again (placeholder not substituted), the
    parse must raise instead of silently analysing an empty description."""
    monkeypatch.setattr(
        ats, "_JD_PROMPT", "You are an analyst.\nJob Description:\nno placeholder here"
    )
    monkeypatch.setattr(
        ats, "_call_gemini", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called"))
    )
    with pytest.raises(GatewayError):
        parse_job_v2("a perfectly ordinary job description", "k", force_refresh=True)



def test_parse_job_v2_bad_json_returns_api_error_default(monkeypatch):
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: "{not valid json")
    job = parse_job_v2("job", "k")
    assert job["_api_error"] is True


def test_calculate_ats_gap_end_to_end(monkeypatch):
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: json.dumps({
        "job_title": "Python Engineer", "experience": {"min_years": 3},
        "required_skills": {"technical": ["Python", "Docker"], "methodologies": [], "tools": []},
        "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
        "languages": [], "certifications": [], "industry": "", "education": {},
    }))
    result = calculate_ats_gap(V3_PROFILE_ROW, "we need a Python engineer", "test-key")
    assert result["ats_score"] >= 90  # Python+Docker are strong candidate hits
    assert result["verdict"]["band"] == "proceed"
    assert result["parsed_job"]["job_title"] == "Python Engineer"
    assert result["hits"] and "Python" in result["hits"]


# ---------------------------------------------------------------------------
# POST /api/ats/analyze (route)
# ---------------------------------------------------------------------------

def test_analyze_requires_auth(client):
    resp = client.post("/api/ats/analyze", json={"job_text": "x"})
    assert resp.status_code == 401


def test_analyze_requires_job_text(client, rsa_material):
    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/ats/analyze",
        json={"job_text": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_analyze_requires_profile(client, rsa_material, monkeypatch):
    import services.api.routers.ats as ats_router

    monkeypatch.setattr(ats_router, "_fetch_own_profile", lambda token: {})
    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/ats/analyze",
        json={"job_text": "Senior role"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "Build your profile" in resp.json()["detail"]


def test_analyze_forwards_token_and_returns_verdict(client, rsa_material, monkeypatch):
    import services.api.routers.ats as ats_router

    captured = {}

    def fake_fetch(token):
        captured["token"] = token
        return {"skills": {"TECHNICAL": ["Python"]}}

    def fake_calc(profile, job_text, api_key, force_refresh=False):
        captured["profile"] = profile
        captured["force_refresh"] = force_refresh
        return {
            "ats_score": 88, "overall_ats": 88.0, "decision": "Strong Match",
            "sub_scores": {}, "gap_analysis": {"missing": [], "strengths": ["Python"]},
            "hard_blockers": [], "verdict": {"band": "proceed", "message": "ok", "proceed": True},
        }

    monkeypatch.setattr(ats_router, "_fetch_own_profile", fake_fetch)
    monkeypatch.setattr(ats_router, "calculate_ats_gap", fake_calc)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/ats/analyze",
        json={"job_text": "Senior role", "force_refresh": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert captured["token"] == token  # RLS: caller's OWN token is forwarded
    assert captured["force_refresh"] is True
    assert resp.json()["verdict"]["band"] == "proceed"


def test_analyze_maps_gateway_failure_to_502(client, rsa_material, monkeypatch):
    import services.api.routers.ats as ats_router

    monkeypatch.setattr(ats_router, "_fetch_own_profile", lambda token: {"skills": {}})
    monkeypatch.setattr(ats_router, "_gemini_key", lambda: "test-key")

    def boom(profile, job_text, api_key, force_refresh=False):
        raise GatewayError("Gemini API Connection Failed.")

    monkeypatch.setattr(ats_router, "calculate_ats_gap", boom)

    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/ats/analyze",
        json={"job_text": "Senior role"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 502


def test_analyze_missing_gemini_key_500(client, rsa_material, monkeypatch):
    import services.api.routers.ats as ats_router

    monkeypatch.setattr(ats_router, "_fetch_own_profile", lambda token: {"skills": {}})
    monkeypatch.setattr(ats_router, "_gemini_key", lambda: "")
    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/ats/analyze",
        json={"job_text": "Senior role"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 500