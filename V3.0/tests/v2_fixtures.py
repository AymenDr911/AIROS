"""Synthetic V2 fixtures covering the required migration test cases.

Deterministic and self-contained (no dependency on the on-disk real snapshot),
so the migration integration tests can always run in CI.

Case coverage map (Test & Migration Validation Plan §2):
  1. New / simple profile          -> newbie@airos.demo  (must be DISCARDED)
  2. Senior profile, long exp      -> senior@career.io   (16+ yrs, strong evidence)
  3. Multiple professional roles   -> senior@career.io   (2 distinct roles)
  4. Multiple certs + skills       -> certified@career.io (5 certs, all categories)
  5. Application w/ recruiter      -> senior@career.io   (recruiter name/email)
  6. Interview-stage application   -> senior@career.io   (status INTERVIEW, timeline)
  7. Rejected application          -> senior@career.io   (status CLOSED, outcome)
  8. Incomplete / legacy data      -> legacy@career.io   (partial record, no profile)
"""

import json
from pathlib import Path
from typing import Any, Dict

_APPS = {
    "APP-20260810-000001": {
        "application_id": "APP-20260810-000001",
        "job_id": "JOB-2026-000001",
        "company_id": "COMP-2026-000001",
        "title": "Senior QA Lead",
        "status": "EMPLOYER_RESPONSE",
        "application_date": "2026-08-10",
        "created_at": "2026-08-10T09:00:00",
        "updated_at": "2026-08-12T11:00:00",
        "ats_score": 91,
        "time_consumed_min": 3,
        "recruiter_name": "Anna",
        "recruiter_email": "anna@recruiter.de",
        "outcome": None,
        "timeline": [
            {"status": "APPLIED", "at": "2026-08-10T09:00:00", "note": ""},
            {"status": "EMPLOYER_RESPONSE", "at": "2026-08-12T11:00:00", "note": ""},
        ],
        "interviews": [],
        "cv_version": "cv_x.txt",
        "cover_letter_version": "cl_x.txt",
        "recruiter_email_path": "re_x.json",
    },
    "APP-20260815-000002": {
        "application_id": "APP-20260815-000002",
        "job_id": "JOB-2026-000001",
        "company_id": "COMP-2026-000002",
        "title": "Quality Director",
        "status": "INTERVIEW",
        "application_date": "2026-08-15",
        "created_at": "2026-08-15T10:00:00",
        "updated_at": "2026-08-16T09:00:00",
        "ats_score": 84,
        "time_consumed_min": 2,
        "recruiter_name": "Maria",
        "recruiter_email": "maria@recruiter.ch",
        "outcome": None,
        "timeline": [
            {"status": "APPLIED", "at": "2026-08-15T10:00:00", "note": ""},
            {"status": "INTERVIEW", "at": "2026-08-16T09:00:00", "note": "round 1"},
        ],
        "interviews": [
            {"round": 1, "scheduled_at": "2026-08-20T10:00:00", "format": "Teams", "notes": ""}
        ],
        "cv_version": "cv_y.txt",
        "cover_letter_version": "cl_y.txt",
        "recruiter_email_path": "",
    },
    "APP-20260818-000003": {
        "application_id": "APP-20260818-000003",
        "job_id": "JOB-2026-000001",
        "company_id": "COMP-2026-000002",
        "title": "QA Manager",
        "status": "CLOSED",
        "application_date": "2026-08-18",
        "created_at": "2026-08-18T10:00:00",
        "updated_at": "2026-08-19T10:00:00",
        "ats_score": 72,
        "time_consumed_min": 1,
        "recruiter_name": "",
        "recruiter_email": "",
        "outcome": {"type": "rejected", "at": "2026-08-19T10:00:00", "note": ""},
        "timeline": [
            {"status": "APPLIED", "at": "2026-08-18T10:00:00", "note": ""},
            {"status": "CLOSED", "at": "2026-08-19T10:00:00", "note": "rejected"},
        ],
        "interviews": [],
        "cv_version": "cv_z.txt",
        "cover_letter_version": "",
        "recruiter_email_path": "",
    },
}


def _profile_senior() -> Dict[str, Any]:
    return {
        "career_stage": "Senior Expert / Manager (8+ years)",
        "personal_identity": {
            "full_name": "SENIOR QA",
            "email": "senior@career.io",
            "phone": "+1 555 0100",
            "location": "Berlin",
            "linkedin": "https://linkedin.com/in/seniorqa",
            "github": "",
            "portfolio": "",
            "summary": "Senior QA engineer with 16+ years.",
        },
        "education": [
            {"degree": "Master", "field": "Computer Science", "institution": "TU Berlin",
             "start_year": "09.2004", "end_year": "06.2006", "description": ""}
        ],
        "experience": [
            {"company": "AlphaCorp", "role": "Senior QA Lead", "location": "Berlin",
             "start_date": "01.2016", "end_date": "Present", "currently_working": True,
             "description": "Leading QA", "achievements": ["Built team"]},
            {"company": "BetaSoft", "role": "QA Engineer / Manager", "location": "Hamburg",
             "start_date": "03.2010", "end_date": "12.2015", "currently_working": False,
             "description": "Managed QA", "achievements": ["Automated 40%"]},
        ],
        "skills": {
            "technical": ["Selenium", "Python"],
            "methodologies": ["Risk Mitigation"],
            "tools": ["Jira"],
            "core": ["Cross-Functional Coordination"],
        },
        "languages": [{"language": "English", "level": "C1"}],
        "certifications": [
            {"name": "ISTQB Advanced", "issuer": "ISTQB", "year": "2019"},
            {"name": "PMP", "issuer": "PMI", "year": "2020"},
        ],
        "original_cv_files": [],
    }


def _profile_certified() -> Dict[str, Any]:
    return {
        "career_stage": "Established (4-7 years)",
        "personal_identity": {"full_name": "CERT USER", "email": "certified@career.io"},
        "experience": [
            {"company": "Gamma", "role": "Dev", "start_date": "06.2019",
             "end_date": "08.2022", "currently_working": False}
        ],
        "skills": {
            "technical": ["Kubernetes", "Docker"],
            "core": ["Stakeholder Management"],
            "methodologies": ["Agile Coaching"],
        },
        "certifications": [
            {"name": "CKA", "issuer": "CNCF", "year": "2021"},
            {"name": "AWS SA Pro", "issuer": "AWS", "year": "2021"},
            {"name": "Security+", "issuer": "CompTIA", "year": "2020"},
            {"name": "Scrum Master", "issuer": "Scrum.org", "year": "2019"},
            {"name": "ITIL 4", "issuer": "Axelos", "year": "2020"},
        ],
        "languages": [{"language": "German", "level": "B2"}],
        "original_cv_files": [],
    }


def build_v2_snapshot_json() -> Dict[str, Any]:
    """Return a fully-populated V2 ``users_db.json``-shaped dict."""
    return {
        # Case 1: demo/test -> must be DISCARDED.
        "newbie@airos.demo": {
            "email": "newbie@airos.demo",
            "password": "Passw0rd!",
            "status": "ACTIVE",
            "created_at": "2026-08-20T09:00:00",
            "verification_token": "AIROS-TEST",
        },
        # Cases 2,3,5,6,7: senior, multi-role, with applications.
        "senior@career.io": {
            "email": "senior@career.io",
            "password": "Hunter2!",
            "status": "ACTIVE",
            "created_at": "2026-08-19T10:00:00",
            "verification_token": "V3-SENIOR-TOKEN",
            "profile": _profile_senior(),
            "applications": _APPS,
        },
        # Case 4: multiple certs + skills.
        "certified@career.io": {
            "email": "certified@career.io",
            "password": "Cert123!",
            "status": "ACTIVE",
            "created_at": "2026-08-18T08:00:00",
            "verification_token": "V3-CERT-TOKEN",
            "profile": _profile_certified(),
        },
        # Case 8: incomplete / legacy — no profile, no apps.
        "legacy@career.io": {
            "email": "legacy@career.io",
            "password": "OldPass1!",
            "status": "PENDING",
            "created_at": "2026-08-01T00:00:00",
            "verification_token": "V3-LEGACY",
        },
    }


def write_synthetic_snapshot(tmp_path: Path) -> Path:
    """Write the synthetic V2 snapshot to a temp file and return its path."""
    p = tmp_path / "users_db.json"
    p.write_text(json.dumps(build_v2_snapshot_json(), indent=2), encoding="utf-8")
    return p