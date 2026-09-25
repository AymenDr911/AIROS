"""CHG-018 — REAL Document-Engine post-generation ATS validation tests.

The Document Engine makes ONE Gemini call; the ATS score is then re-validated
deterministically (ai/document_validation.py -> compute_ats_engine, NO new AI
call). These tests prove:

- the tailored score reported by the engine is the deterministic recomputation;
- improvement  = tailored_ats - original_ats (never a silent regression);
- needs_review is raised whenever the CV regressed OR fabricated content,
  even if the raw score happened to improve;
- fabrication/evidence guards catch skills/certs/companies absent from the
  profile.

Compare with the V2 post-generation validation spec (V2 app/utils/validation.py
Step 11): identical semantics — evidence validation -> fabrication check ->
ATS recalculation -> needs_review.
"""

from ai.ats import build_candidate_json, compute_ats_engine
from ai.document_validation import validate_generated_documents


def _profile_row():
    """Realistic candidate standing in as the caller's V3 profile row."""
    return {
        "skills": {
            "TECHNICAL": ["Python", "Docker", "PostgreSQL"],
            "MANAGEMENT": ["Agile"],
        },
        "experience": [
            {"company": "Acme", "title": "Engineer", "start_date": "01.2016",
             "end_date": "Present", "currently_working": True},
            {"company": "Beta", "title": "DevOps", "start_date": "03.2014",
             "end_date": "12.2015"},
        ],
        "languages": [{"language": "English", "level": "C1"}],
        "certifications": [{"name": "PMP", "issuer": "PMI", "year": "2020"}],
    }


def _candidate():
    return build_candidate_json(_profile_row())


def _parsed_job():
    """Parsed JD shape (stored in jobs.job_json) with real requirements."""
    return {
        "job_title": "Senior Python Engineer",
        "company_name": "Siemens AG",
        "experience": {"min_years": 3, "preferred_years": 5},
        "education": {"min_degree": "", "preferred_fields": []},
        "languages": [{"language": "English", "level": "C1", "required": True}],
        "required_skills": {
            "technical": ["Python", "Docker", "Kubernetes", "Go"],
            "methodologies": ["Agile"],
            "tools": [],
        },
        "certifications": [],
    }


def _job(original_ats: int) -> dict:
    """The saved jobs row seen by the validation step (router input)."""
    return {"ats_score": original_ats, "title": "Senior Python Engineer",
            "job_json": _parsed_job()}


def _cv(skills: dict, **extra) -> dict:
    cv = {
        "full_text": "Tailored CV text",
        "skills": skills,
        "experience": [{"company": "Acme", "title": "Engineer",
                        "start_date": "01.2016", "end_date": "Present"}],
        "languages": [{"language": "English", "level": "C1"}],
        "certifications": [{"name": "PMP", "issuer": "PMI", "year": "2020"}],
        "education": [{"degree": "Master of Science"}],
    }
    cv.update(extra)
    return cv


def _generated(skills: dict) -> dict:
    """Structured output of the (mocked) Document Engine generation call."""
    return {
        "cv": _cv(skills,
                  optimization_report={"gaps_not_claimed": ["Go"],
                                       "evidence_based": True}),
        "cover_letter": {"full_text": "DEAR HIRING TEAM"},
        "recruiter_email": {"required": True, "to": "hiring@acme.example",
                            "subject": "Application", "body": "Hello"},
        "optimization_report": {"target_keywords_used": ["python"],
                                "gaps_not_claimed": ["Go"],
                                "evidence_based": True},
    }


def _gen_profile(gen, candidate):
    """Rebuild the pool exactly as _recalculate_ats does (incl. the
    total_experience_years fallback, the TOOLS category and the
    summary/full_text token enrichment)."""
    import re as _re

    cv = gen["cv"]
    profile = {
        "skills": {"TECHNICAL": cv["skills"].get("technical", []),
                   "MANAGEMENT": cv["skills"].get("methodologies", []),
                   "TOOLS": cv["skills"].get("tools", [])},
        "languages": cv.get("languages", []),
        "certifications": cv.get("certifications", []),
        "education": cv.get("education", []),
        "experience": cv.get("experience", []),
    }
    rebuilt = build_candidate_json(profile)
    rebuilt["total_experience_years"] = candidate.get("total_experience_years", 0)
    cv_text = " ".join([str(cv.get("summary") or ""), str(cv.get("full_text") or "")])
    tokens = set(rebuilt.get("all_tokens") or [])
    tokens.update(_re.findall(r"[A-Za-z][A-Za-z0-9\+\#\.]{2,}", cv_text.lower()))
    rebuilt["all_tokens"] = sorted(tokens)
    return rebuilt
# ---------------------------------------------------------------------------
# 1. The reported tailored score = the deterministic recomputation
# ---------------------------------------------------------------------------
def test_reported_tailored_score_is_the_deterministic_recompute():
    cand = _candidate()
    job = _job(original_ats=55)
    good_skills = {"technical": ["Python", "Docker", "PostgreSQL"],
                   "methodologies": ["Agile"], "tools": []}
    gen = _generated(good_skills)
    report = validate_generated_documents(gen, job, cand)

    # No new model call: the score must equal the deterministic engine
    # re-run on the generated CV's own data.
    expected = compute_ats_engine(_gen_profile(gen, cand), _parsed_job())
    assert report["ats_recalculation"]["overall_ats"] == expected["overall_ats"]
    assert report["tailored_ats"] == int(round(expected["overall_ats"]))
    assert report["original_ats"] == 55
    assert report["improvement"] == report["tailored_ats"] - 55
    assert report["tailored_ats"] > 55
    assert report["status"] == "improved"
    assert report["needs_review"] is False


def test_reported_improvement_is_original_minus_recomputed():
    # Original stored score is the baseline; improvement is relative to it.
    cand = _candidate()
    job = _job(original_ats=55)
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL"],
                      "methodologies": ["Agile"], "tools": []})
    report = validate_generated_documents(gen, job, cand)
    expected = int(round(compute_ats_engine(_gen_profile(gen, cand), _parsed_job())
                         ["overall_ats"]))
    assert report["improvement"] == expected - 55
    assert (report["tailored_ats"] - report["original_ats"]) == report["improvement"]


# ---------------------------------------------------------------------------
# 2. No regressed CV is ever silently presented as optimized
# ---------------------------------------------------------------------------
def test_regression_is_flagged_even_without_fabrication():
    cand = _candidate()
    job = _job(original_ats=92)  # high original
    # The generated CV keeps only Python -> the recomputation drops hard.
    gen = _generated({"technical": ["Python"]})
    report = validate_generated_documents(gen, job, cand)

    assert report["original_ats"] == 92
    assert report["tailored_ats"] < 92
    assert report["improvement"] < 0
    assert report["status"] == "regressed"
    assert report["needs_review"] is True  # never silently accepted


# ---------------------------------------------------------------------------
# 3. Fabrication guard triggers needs_review even when the score improves
# ---------------------------------------------------------------------------
def test_fabricated_skill_sets_needs_review():
    cand = _candidate()
    job = _job(original_ats=55)
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL",
                                    "Go", "terraform"]})  # Go/terraform absent
    report = validate_generated_documents(gen, job, cand)

    assert report["fabrication_check"]["fabrications_found"] is True
    types = {f["type"] for f in report["fabrication_check"]["fabrications"]}
    assert "skill" in types
    assert report["evidence_validation"]["all_evidence_supported"] is False
    assert report["needs_review"] is True


def test_fabricated_certification_detected():
    cand = _candidate()
    gen = _generated({"technical": ["Python"]})
    gen["cv"]["certifications"] = [{"name": "AWS Certified", "issuer": "AWS"}]
    report = validate_generated_documents(gen, _job(55), cand)
    types = {f["type"] for f in report["fabrication_check"]["fabrications"]}
    assert "certification" in types
    assert report["needs_review"] is True


# ---------------------------------------------------------------------------
# 4. Unchanged score -> consistent report, no false alarm
# ---------------------------------------------------------------------------
def test_unchanged_documents_report_unchanged():
    cand = _candidate()
    job = _job(original_ats=80)
    gen = _generated({"technical": ["Python"]})
    report = validate_generated_documents(gen, job, cand)
    assert report["tailored_ats"] == int(round(report["ats_recalculation"]["overall_ats"]))
    assert report["improvement"] == report["tailored_ats"] - 80
    # A sub-2-point delta is now reported as the honest "marginal" status
    # (CHG-021: AIROS tells the user it could not do more instead of claiming
    # a meaningless +1-point "improvement").
    assert report["status"] in {"improved", "regressed", "marginal"}


# ---------------------------------------------------------------------------
# CHG-021 - objective re-scoring + honest marginal-gain reporting
# (manual-test feedback: "80 -> 81 is not enough", "< 2% -> let the user choose")
# ---------------------------------------------------------------------------
def test_tools_from_generated_cv_are_scored():
    """The re-scored candidate must include the tools category - before the fix
    _recalculate_ats silently dropped it, systematically under-scoring tailored
    CVs (objectivity defect)."""
    profile = dict(_profile_row())
    # Jira is PROVEN by a real achievement so the tailored CV may list it
    # without tripping the fabrication guard.
    profile["experience"] = [
        {"company": "Acme", "title": "Engineer", "start_date": "01.2016",
         "end_date": "Present", "currently_working": True,
         "achievements": ["Adopted Jira for sprint tracking of the delivery team"]},
        {"company": "Beta", "title": "DevOps", "start_date": "03.2014",
         "end_date": "12.2015"},
    ]
    cand = build_candidate_json(profile)
    job_json = dict(_parsed_job())
    job_json["required_skills"]["tools"] = ["Jira"]
    job = {"ats_score": 1, "title": "Senior Python Engineer", "job_json": job_json}
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL"],
                      "methodologies": ["Agile"], "tools": ["Jira"]})

    report = validate_generated_documents(gen, job, cand)
    assert report["ats_recalculation"]["sub_scores"]["tools"] == 100.0
    assert report["fabrication_check"]["fabrications_found"] is False
    assert report["needs_review"] is False


def test_cv_text_keywords_are_credited_in_recompute():
    """Absolute objectivity: the final document text (summary + full_text) is
    what a real ATS parses, so a required keyword PRINTED in the generated CV
    is credited by the recomputed score even when it is not in the structured
    skills list."""
    profile = dict(_profile_row())
    # Kubernetes is proven by the profile experience but NOT in the structured
    # skills list - exactly the "rich experience behind the skills" case.
    profile["experience"] = [
        {"company": "Acme", "title": "Platform Engineer", "start_date": "01.2019",
         "end_date": "Present", "currently_working": True,
         "achievements": ["Operated production Kubernetes clusters for the SaaS platform"]},
    ]
    cand = build_candidate_json(profile)
    job = _job(original_ats=1)
    gen = _generated({"technical": ["Python"], "methodologies": [], "tools": []})
    gen["cv"]["summary"] = "Platform engineer operating Kubernetes daily."
    gen["cv"]["full_text"] = "Ran Kubernetes production clusters and Go-based services at Acme."

    report = validate_generated_documents(gen, job, cand)
    tech = report["ats_recalculation"]["sub_scores"]["technical_skills"]
    # Python (exact) + Kubernetes (document text token) = 2 of 4 required -> 50.
    assert tech == 50.0
    # Kubernetes is truthful (in the profile) so nothing is flagged as
    # fabricated even though the structured skills list did not carry it.
    assert report["fabrication_check"]["fabrications_found"] is False


def test_fabricated_free_text_keyword_is_flagged():
    """A job-required keyword PRINTED in the generated CV but NOT provable from
    the profile would inflate the objective recompute - the validation must flag
    it as a fabrication and request review (no invented skills, ever)."""
    cand = _candidate()  # has no Kubernetes anywhere in the profile
    job = _job(original_ats=1)
    gen = _generated({"technical": ["Python"], "methodologies": [], "tools": []})
    gen["cv"]["summary"] = "Certified Kubernetes administrator with 5 years of Kubernetes."

    report = validate_generated_documents(gen, job, cand)
    assert report["fabrication_check"]["fabrications_found"] is True
    assert "kubernetes" in report["fabrication_check"].get("text_fabrications", [])
    assert report["needs_review"] is True


def test_empty_candidate_pool_never_auto_passes():
    # Even an empty candidate pool must not crash AND must not auto-pass.
    cand = build_candidate_json({})
    gen = _generated({"technical": ["Python"]})
    report = validate_generated_documents(gen, _job(80), cand)
    assert report["needs_review"] is True
    assert report["original_ats"] == 80


# ---------------------------------------------------------------------------
# CHG-021 - honest marginal-gain reporting + objectivity + prompt strategy
# ---------------------------------------------------------------------------
def test_marginal_gain_below_two_points_reports_choice():
    """improvement in [0, 2) points -> status 'marginal' + the honest message
    telling the user AIROS could not do more and they may pick either CV."""
    cand = _candidate()
    job = _job(original_ats=1)  # placeholder; recompute is what matters
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL"],
                      "methodologies": ["Agile"], "tools": []})

    reference = validate_generated_documents(gen, job, cand)
    real_score = int(round(reference["ats_recalculation"]["overall_ats"]))

    forced = _job(original_ats=real_score - 1)  # exactly +1 point -> marginal
    report = validate_generated_documents(gen, forced, cand)

    assert report["tailored_ats"] - report["original_ats"] == 1
    assert report["improvement"] == 1
    assert report["status"] == "marginal"
    assert report["marginal_gain_threshold"] == 2.0
    assert "free" in report["message"].lower()
    assert "choose" in report["message"].lower()
    assert report["needs_review"] is False


def test_improvement_two_points_or_more_reports_improved():
    cand = _candidate()
    job = _job(original_ats=1)
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL"],
                      "methodologies": ["Agile"], "tools": []})

    reference = validate_generated_documents(gen, job, cand)
    real_score = int(round(reference["ats_recalculation"]["overall_ats"]))

    forced = _job(original_ats=real_score - 3)  # +3 points -> real improvement
    report = validate_generated_documents(gen, forced, cand)
    assert report["improvement"] == 3
    assert report["status"] == "improved"
    assert report["needs_review"] is False


def test_validation_marks_itself_objective():
    """The validation report must flag the tailored score as a deterministic
    recomputation (no AI round-trip) so the displayed comparison is auditable."""
    cand = _candidate()
    gen = _generated({"technical": ["Python", "Docker", "PostgreSQL"],
                      "methodologies": ["Agile"], "tools": []})
    report = validate_generated_documents(gen, _job(original_ats=1), cand)
    assert report["objective"] is True
    assert "deterministic" in report["objective_note"].lower()
    assert "no ai" in report["objective_note"].lower()
    # The reported overall equals the deterministic engine re-run on the same
    # generated content (mirrored by the test helper - no model round-trip).
    assert report["ats_recalculation"]["overall_ats"] == float(
        compute_ats_engine(_gen_profile(gen, cand), _parsed_job())["overall_ats"])


def test_generation_prompt_teaches_ats_keyword_alignment():
    """The re-engineered Gemini prompt (CHG-021) instructs the model to SURFACE
    every PROVABLE job keyword truthfully - including experience-derived facts
    (industry, DACH links, client nationality, language of work) - and to keep
    unprovable gaps out of the CV text."""
    import ai.documents as docs_engine

    prompt = docs_engine._build_generation_prompt(
        candidate=_candidate(),
        job={"ats_score": 80, "job_json": _parsed_job()},
        parsed_job=_parsed_job(),
        company={},
        reliable_contact=None,
        generate_cv=True,
        generate_cover_letter=True,
        generate_recruiter_email=True,
    )
    assert "ATS keyword alignment strategy" in prompt
    assert "PROVABLE" in prompt
    assert "gaps_not_claimed" in prompt
    assert "ministry of defence" in prompt.lower()  # the DACH reframing example
    assert "Never write" in prompt and "gap" in prompt.lower()  # no negatives in the CV
    # No reliable contact -> the recruiter email generation is disabled in the
    # prompt itself (RH mailing removed, workflow NOT blocked).
    assert "Generate Recruiter Email: False" in prompt


# ---------------------------------------------------------------------------
# REGRESSION: the REAL Document Engine + the REAL candidate builder
# (CHG-018 USER BUG: "Load Failed / no generated doc" on Generate)
#
# build_candidate_json() used to return all_tokens as a SET, so the engine's
# json.dumps(candidate) raised "TypeError: Object of type set is not JSON
# serializable" on EVERY generation and the endpoint errored before any AI
# call. The offline API suite missed it because it mocks the engine at the
# router boundary. This test drives the exact live path (real builder -> real
# prompt serialization -> mocked Gemini) and must produce documents.
# ---------------------------------------------------------------------------
def test_document_engine_generates_with_real_candidate_builder(monkeypatch):
    import json as _json

    import ai.documents as docs_engine
    from ai.documents import generate_application_documents

    cand = _candidate()
    # V2 parity (V2 ats.py returns sorted(...)): all_tokens must be a
    # JSON-serializable LIST here - a set crashes json.dumps() in the engine.
    assert isinstance(cand["all_tokens"], list)
    assert cand["all_tokens"] == sorted(cand["all_tokens"])

    job = dict(_job(original_ats=55))
    job["job_id"] = "JOB-TEST"
    company = {"company_id": "C1", "name": "Siemens AG"}
    contacts = [{"contact_id": "K1", "name": "Max", "position": "Talent Acquisition",
                 "email": "max.recruiter@acme.example", "confidence": "High"}]

    gemini_reply = {
        "cv": {"full_text": "TAILORED CV TEXT",
               "skills": {"technical": ["Python"], "methodologies": ["Agile"], "tools": []}},
        "cover_letter": {"full_text": "DEAR HIRING TEAM"},
        "recruiter_email": {"required": True, "to": "max.recruiter@acme.example",
                            "subject": "Application", "body": "Hello"},
        "optimization_report": {"target_keywords_used": ["python"],
                                "gaps_not_claimed": [], "evidence_based": True},
    }
    monkeypatch.setattr(
        docs_engine, "_call_gemini",
        lambda prompt, api_key, json_mode=False: _json.dumps(gemini_reply),
    )

    out = generate_application_documents(cand, job, company, contacts, "test-key")
    assert out["cv"]["full_text"] == "TAILORED CV TEXT"
    assert out["recruiter_email"]["required"] is True
    assert out["recruiter_contact"]["email"] == "max.recruiter@acme.example"


def test_json_safe_guard_coerces_non_serializable_values():
    """The engine's _json_safe() must coerce any set/tuple so json.dumps()
    can never crash the endpoint (the user-reported CHG-018 failure)."""
    import json as _json

    import ai.documents as docs_engine

    hostile = {
        "all_tokens": {"python", "agile"},
        "pair": ("a", "b"),
        "nested": [{"tags": {"x", "y"}}],
    }
    safe = docs_engine._json_safe(hostile)
    assert safe["all_tokens"] == ["agile", "python"]
    assert safe["pair"] == ["a", "b"]
    assert safe["nested"][0]["tags"] == ["x", "y"]
    assert _json.dumps(safe)  # must serialize cleanly