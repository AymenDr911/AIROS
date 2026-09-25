"""AIROS V3 - Application lifecycle tests (CHG-018).

Pure deterministic port tests of the V2 tracker semantics (no IO):
- manual-only transition matrix (invalid moves rejected, terminal CLOSED),
- outcome recording on REJECTED / OFFER / WITHDRAWN,
- recruiter-response outcome mapping (REFUSED -> REJECTED, INTERVIEW_REQUEST
  -> INTERVIEW + pending round, ADDITIONAL_INFO_REQUEST -> ADDITIONAL_INFO),
- follow-up as an ACTION (status stays WAITING; checkpoint moves),
- record creation parity (snapshot, follow-up checkpoint = date + 8 days,
  time consumed from the document generation timestamp),
- next-action priority (Rule 1 > Rule 2 > Rule 3),
- deterministic V2-style sequential IDs.
"""

from __future__ import annotations

import pytest

from ai import lifecycle as lc


# ---------------------------------------------------------------- transitions
def test_applied_to_waiting_is_valid():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    lc.update_status_record(app, lc.WAITING)
    assert app["status"] == lc.WAITING
    assert app["timeline"][-1]["status"] == lc.WAITING


def test_invalid_transition_is_rejected():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    with pytest.raises(lc.TransitionError, match="Invalid transition from APPLIED to OFFER"):
        lc.update_status_record(app, lc.OFFER)
    assert app["status"] == lc.APPLIED  # unchanged


def test_interview_to_interview_means_next_round():
    app = {"status": lc.INTERVIEW, "timeline": []}
    lc.update_status_record(app, lc.INTERVIEW, note="Round 2")
    assert app["status"] == lc.INTERVIEW


def test_closed_is_terminal():
    assert lc.get_valid_transitions(lc.CLOSED) == []
    app = {"status": lc.CLOSED, "timeline": []}
    with pytest.raises(lc.TransitionError):
        lc.update_status_record(app, lc.WAITING)


def test_outcome_recorded_on_terminal_statuses():
    # WAITING -> OFFER is NOT a valid manual move (V2 map); use INTERVIEW -> OFFER.
    app = {"status": lc.INTERVIEW, "timeline": []}
    lc.update_status_record(app, lc.OFFER, note="signed")
    assert app["outcome"] == "offer"
    assert app["outcome_detail"]["type"] == "offer"

    app2 = {"status": lc.APPLIED, "timeline": []}
    lc.update_status_record(app2, lc.REJECTED)
    assert app2["outcome"] == "rejected"

    app3 = {"status": lc.APPLIED, "timeline": []}
    lc.update_status_record(app3, lc.WITHDRAWN)
    assert app3["outcome"] == "withdrawn"


def test_close_only_from_terminal_outcomes():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    with pytest.raises(lc.TransitionError, match="final outcomes"):
        lc.close_application_record(app)

    lc.update_status_record(app, lc.REJECTED)   # APPLIED -> REJECTED is valid
    assert app["outcome"] == "rejected"
    lc.close_application_record(app, note="done")
    assert app["status"] == lc.CLOSED
    assert app["outcome"] == "rejected"  # outcome kept from the rejection


# ---------------------------------------------------------------- responses
def test_refused_response_maps_to_rejected():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    lc.record_employer_response_record(app, lc.RESPONSE_REFUSED, channel="Email")
    assert app["status"] == lc.REJECTED
    assert app["outcome"] == "rejected"
    assert app["recruiter_responses"][-1]["type"] == lc.RESPONSE_REFUSED


def test_interview_request_maps_to_interview_with_pending_round():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    lc.record_employer_response_record(app, lc.RESPONSE_INTERVIEW, channel="Phone")
    assert app["status"] == lc.INTERVIEW
    pending = lc.find_pending_interview(app)
    assert pending is not None
    assert pending["round"] == 1
    assert pending["requested"] is True
    assert pending["scheduled_at"] == ""


def test_additional_info_response_maps_to_additional_info():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    lc.record_employer_response_record(app, lc.RESPONSE_ADDITIONAL_INFO, channel="Email")
    assert app["status"] == lc.ADDITIONAL_INFO


def test_invalid_response_type_and_missing_channel_raise():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    with pytest.raises(ValueError, match="Unknown response type"):
        lc.record_employer_response_record(app, "MAYBE")
    with pytest.raises(ValueError, match="communication channel"):
        lc.record_employer_response_record(app, lc.RESPONSE_REFUSED, channel="")


def test_response_from_closed_state_is_rejected():
    app = {"status": lc.CLOSED, "timeline": []}
    with pytest.raises(lc.TransitionError):
        lc.record_employer_response_record(app, lc.RESPONSE_REFUSED, channel="Email")


# ---------------------------------------------------------------- follow-up
def test_mark_contacted_only_valid_while_waiting():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    with pytest.raises(lc.TransitionError, match="only valid while"):
        lc.mark_contacted_record(app)

    lc.update_status_record(app, lc.WAITING)
    checkpoint_before = app["follow_up_checkpoint"]
    lc.mark_contacted_record(app, contacted_at="2026-09-09", channel="Email", note="polite ping")
    assert app["status"] == lc.WAITING  # action, not a status change
    assert len(app["follow_ups"]) == 1
    assert app["follow_ups"][0]["sent_date"] == "2026-09-09"
    assert app["follow_up_checkpoint"] >= checkpoint_before
    assert app["timeline"][-1]["event"] == "contacted"


def test_remind_me_later_pushes_checkpoint():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    lc.update_status_record(app, lc.WAITING)
    before = app["follow_up_checkpoint"]
    lc.remind_me_later_record(app, days=30)
    assert app["follow_up_checkpoint"] > before
    assert lc.next_action(app)["action"] == "Send / prepare a follow-up"


def test_draft_follow_up_mentions_job_and_company():
    app = lc.create_application_record(
        "APP-2026-000001",
        {"job_id": "JOB-1", "title": "Data Engineer", "company_id": "COMP-1"},
        company_name="Acme",
    )
    draft = lc.draft_follow_up(app)
    assert "Data Engineer" in draft["message"]
    assert "Acme" in draft["message"]


def test_dates_require_valid_input():
    app = lc.create_application_record("APP-2026-000001", {"job_id": "JOB-1"})
    with pytest.raises(ValueError, match="employer response date"):
        lc.set_employer_response_date_record(app, "not-a-date")
    lc.set_employer_response_date_record(app, "2026-10-01")
    assert app["employer_response_date"] == "2026-10-01"
    with pytest.raises(ValueError, match="job closing date"):
        lc.set_job_closing_date_record(app, "")
    lc.set_job_closing_date_record(app, "2026-09-30")
    assert app["job_closing_date"] == "2026-09-30"


# ---------------------------------------------------------------- record creation
def test_create_application_record_v2_parity():
    job = {
        "job_id": "JOB-2026-000001",
        "company_id": "COMP-2026-000001",
        "title": "Nurse",
        "location": "Berlin",
        "country": "Germany",
        "job_url": "https://x",
        "source": "Manual paste",
        "ats_score": 85,
        "job_json": {"application_deadline": "2026-10-15"},
    }
    app = lc.create_application_record(
        "APP-2026-000001", job,
        company_name="Charite",
        channel="Job Platform (LinkedIn)",
        application_date="2026-09-09",
        notes="applied via app",
        recruiter={"contact_id": "CONT-1", "name": "Anna", "email": "anna@x.de"},
        docs={"cv_path": "local://cv.txt", "cover_letter_path": "local://cl.txt"},
        docs_generated_at="2026-09-09T10:00:00",
        now="2026-09-09T10:30:00",
    )
    assert app["status"] == lc.APPLIED
    assert app["title"] == "Nurse"
    assert app["company_name"] == "Charite"
    assert app["ats_score"] == 85
    assert app["recruiter_name"] == "Anna"
    assert app["cv_version"] == "local://cv.txt"
    assert app["time_consumed_min"] == 30  # generation -> confirmation
    assert app["follow_up_checkpoint"] == "2026-09-17"  # +8 calendar days
    assert app["job_closing_date"] == "2026-10-15"  # Rule 2 extracted from the JD
    assert app["timeline"][0]["status"] == lc.APPLIED


# ---------------------------------------------------------------- next action
def test_next_action_rules_priority():
    base = lc.create_application_record("APP-1", {"job_id": "JOB-1"}, application_date="2026-09-01")
    assert lc.next_action(base)["source"] == lc.NEXT_ACTION_SOURCE_CONFIG  # Rule 3 default

    waiting = dict(base, status=lc.WAITING)
    lc.set_employer_response_date_record(waiting, "2026-10-01")
    assert "employer_response_date" in lc.next_action(waiting)["source"]  # Rule 1 wins

    waiting2 = dict(base, status=lc.WAITING)
    lc.set_job_closing_date_record(waiting2, "2026-09-20")
    assert "job_closing_date" in lc.next_action(waiting2)["source"]  # Rule 2 when no Rule 1

    waiting3 = dict(base, status=lc.WAITING)
    assert lc.next_action(waiting3)["action"].startswith("Send / prepare a follow-up")
    lc.mark_contacted_record(waiting3)
    assert lc.next_action(waiting3)["action"].startswith("Keep waiting")


def test_create_application_logs_initial_recruiter_snapshot_and_approval_timestamp():
    """CHG-023: the tracking record captures the recruiter interaction snapshot
    (recruiter_interactions is never silently empty) and the workspace approval
    datetime (docs_approved_at) for accurate duration calculations."""
    job = {"job_id": "JOB-2026-000001", "company_id": "COMP-2026-000001",
           "title": "Nurse", "ats_score": 85, "job_json": {}}
    app = lc.create_application_record(
        "APP-2026-000001", job,
        company_name="Charite",
        recruiter={"contact_id": "CONT-7", "name": "Anna", "email": "anna@x.de",
                   "position": "Talent Acquisition", "linkedin_url": "https://li/anna",
                   "phone": "+49 170 1234567"},
        docs_generated_at="2026-09-09T10:00:00",
        docs_approved_at="2026-09-09T10:05:00",
        now="2026-09-09T10:30:00",
    )
    assert app["docs_approved_at"] == "2026-09-09T10:05:00"
    assert app["time_consumed_min"] == 30  # generation -> confirmation
    # Recruiter snapshot landed in the interactions audit trail.
    interactions = app["recruiter_interactions"]
    assert len(interactions) == 1
    entry = interactions[0]
    assert entry["type"] == "recruiter_contact_initial"
    assert entry["name"] == "Anna"
    assert entry["phone"] == "+49 170 1234567"
    # No recruiter -> no fabricated initial interaction.
    plain = lc.create_application_record("APP-2026-000002", job, now="2026-09-09T10:30:00")
    assert plain["recruiter_interactions"] == []
    assert plain["docs_approved_at"] == ""


def test_next_action_interview_pending():
    app = lc.create_application_record("APP-1", {"job_id": "JOB-1"})
    lc.record_employer_response_record(app, lc.RESPONSE_INTERVIEW, channel="Phone")
    action = lc.next_action(app)
    assert action["action"] == "Schedule the requested interview"


# ---------------------------------------------------------------- ids
def test_sequential_ids():
    assert lc.next_sequential_id("JOB", []) == f"JOB-{lc.datetime.now().year}-000001"
    year = lc.datetime.now().year
    assert lc.next_sequential_id("JOB", [f"JOB-{year}-000003", f"JOB-{year - 1}-000099"]) \
        == f"JOB-{year}-000004"
    assert lc.next_sequential_id("APP", [f"APP-{year}-garbage"]) == f"APP-{year}-000001"

