"""Migration integration + unit tests (Test & Migration Validation Plan §2).

Covers:
- the pipeline (extract -> transform -> reconcile) against a synthetic snapshot,
- the register's safety rules (discard demo/test user + plaintext password +
  inline base64 CV never carried),
- the 8 required migration test cases,
- a real-snapshot smoke test (skipped gracefully when V2 data is absent).
"""

import json

import pytest

from migration.runner import run_migration, save_report
from migration.snapshot import load_snapshot, SnapshotNotFoundError
from migration.transform import reclassify_skills, has_strength_evidence, transform_users
from migration.reconcile import KNOWN_LIFECYCLE
from tests.v2_fixtures import write_synthetic_snapshot


@pytest.fixture
def snapshot(tmp_path):
    p = write_synthetic_snapshot(tmp_path)
    return load_snapshot(str(p))


# ---------------------------------------------------------------------------
# Unit: skill classification
# ---------------------------------------------------------------------------

class TestSkillClassification:
    def test_maps_source_categories(self):
        out = reclassify_skills({"technical": ["Python"], "tools": ["Jira"], "core": ["X"]})
        assert "Python" in out["TECHNICAL"]
        assert "Jira" in out["TECHNICAL"]      # tools -> technical
        assert "X" in out["CORE"]

    def test_keyword_disambiguation(self):
        assert reclassify_skills({"misc": ["Team Leadership"]})["MANAGEMENT"]
        assert reclassify_skills({"misc": ["Team Collaboration"]})["SOFT"]
        assert reclassify_skills({"misc": ["Docker"]})["TECHNICAL"]

    def test_categories_always_present(self):
        out = reclassify_skills(None)
        assert set(out.keys()) == {"TECHNICAL", "CORE", "MANAGEMENT", "SOFT", "OTHER"}


# ---------------------------------------------------------------------------
# Unit: strong-evidence detection (case 2)
# ---------------------------------------------------------------------------

class TestStrengthEvidence:
    def test_long_tenure_detected(self):
        exp = [{"start_date": "01.2016", "end_date": "01.2022", "currently_working": False}]
        assert has_strength_evidence(exp) is True

    def test_short_tenure_not_detected(self):
        exp = [{"start_date": "01.2021", "end_date": "06.2022", "currently_working": False}]
        assert has_strength_evidence(exp) is False

    def test_open_ended_active_counts(self):
        exp = [{"start_date": "01.2016", "end_date": "Present", "currently_working": True}]
        assert has_strength_evidence(exp) is True

    def test_empty_is_false(self):
        assert has_strength_evidence([]) is False


# ---------------------------------------------------------------------------
# Unit: lifecycle status consistency
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_known_statuses_covered(self):
        # Statuses seen in the real V2 data must be recognized by the reconcile check.
        for st in ("APPLIED", "INTERVIEW", "EMPLOYER_RESPONSE", "CLOSED", "OFFER"):
            assert st in KNOWN_LIFECYCLE


# ---------------------------------------------------------------------------
# Pipeline: safety rules + 8 migration cases
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_discards_demo_user_keeps_real(self, snapshot):
        result = transform_users(snapshot)
        emails = {u.email for u in result.users}
        assert "newbie@airos.demo" not in emails       # case 1: demo discarded
        assert "senior@career.io" in emails            # case 2/3
        assert "certified@career.io" in emails         # case 4
        assert "legacy@career.io" in emails            # case 8

    def test_no_password_and_no_base64_carried(self, snapshot):
        result = transform_users(snapshot)
        for u in result.users:
            assert "password" not in u.profile
        for d in result.documents:
            assert "content_base64" not in d

    def test_applications_and_lifecycle_preserved(self, snapshot):
        result = transform_users(snapshot)
        senior = next(u for u in result.users if u.email == "senior@career.io")
        statuses = {a["status"] for a in senior.applications}
        assert statuses == {"EMPLOYER_RESPONSE", "INTERVIEW", "CLOSED"}
        # recruiter preserved (case 5), interview present (case 6), outcome (case 7)
        with_recruiter = [a for a in senior.applications if a["recruiter_name"]]
        assert with_recruiter and with_recruiter[0]["recruiter_email"]
        interview = [a for a in senior.applications if a["status"] == "INTERVIEW"][0]
        assert interview["interviews"] and interview["timeline"]
        rejected = [a for a in senior.applications if a["status"] == "CLOSED"][0]
        assert rejected["outcome"] and rejected["outcome"]["type"] == "rejected"

    def test_reconcile_passes_on_clean_snapshot(self, snapshot):
        report = run_migration(str(snapshot.path))
        assert report.ok, report.errors
        assert report.counts["src_apps"] == 3
        assert report.counts["dst_apps"] == 3

    def test_save_report_roundtrip(self, snapshot, tmp_path):
        report = run_migration(str(snapshot.path))
        out = tmp_path / "report.json"
        save_report(report, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["ok"] is True
        assert data["counts"]["dst_apps"] == 3


# ---------------------------------------------------------------------------
# Real-snapshot smoke test (skipped when V2 data not present)
# ---------------------------------------------------------------------------

class TestRealSnapshot:
    def test_real_snapshot_reconciles(self):
        try:
            report = run_migration()
        except SnapshotNotFoundError:
            pytest.skip("Real V2 snapshot not available on this machine")
        # Demo user must be discarded; real user's 4 applications preserved.
        assert report.ok, report.errors
        assert "test@airos.demo" not in {u["email"] for u in report.users}
        assert report.counts["dst_apps"] == 4