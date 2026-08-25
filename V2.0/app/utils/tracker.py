# app/utils/tracker.py
"""
AIROS V2 — Post-Application Job Tracker Service
================================================

This is the final stage of the AIROS V2 workflow. It starts immediately after the
user confirms that an application has been submitted.

The tracker is intentionally MANUAL and CONSERVATIVE:
- AIROS never assumes an application has progressed unless the user confirms it.
- Every lifecycle transition requires an explicit user action.
- No application is forced through every stage (APPLIED → INTERVIEW → OFFER is valid,
  APPLIED → REJECTED is also valid).

Lifecycle (from the V2 spec):

APPLIED
   ├──► WAITING  ──► FOLLOW-UP ──► WAITING  (loop)
   ▼
EMPLOYER_RESPONSE
   ├──► SCREENING
   ├──► INTERVIEW      ──► NEXT ROUND / OFFER / REJECTED / WITHDRAWN
   ├──► ASSESSMENT     ──► NEXT ROUND / OFFER / REJECTED / WITHDRAWN
   ├──► ADDITIONAL_INFO
   └──► REJECTED  ──► CLOSED

REJECTED / OFFER / WITHDRAWN are terminal outcomes; closing moves them to CLOSED.

Persistence follows the per-user pattern used by services/profile_service.py:
the record is stored under data/users_db.json -> <user_email> -> "applications",
so it survives app restarts.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# ==============================================================================
# 1. STATUS VOCABULARY
# ==============================================================================
APPLIED           = "APPLIED"
WAITING           = "WAITING"
FOLLOW_UP         = "FOLLOW_UP"
EMPLOYER_RESPONSE = "EMPLOYER_RESPONSE"
SCREENING         = "SCREENING"
INTERVIEW         = "INTERVIEW"
ASSESSMENT        = "ASSESSMENT"
ADDITIONAL_INFO   = "ADDITIONAL_INFO"
OFFER             = "OFFER"
REJECTED          = "REJECTED"
WITHDRAWN         = "WITHDRAWN"
CLOSED            = "CLOSED"

# Human-friendly labels (shown in the UI)
STATUS_LABELS = {
    APPLIED:           "📥 Applied",
    WAITING:           "⏳ Waiting",
    FOLLOW_UP:         "📤 Follow-up (action)",  # NOT a lifecycle status — kept for UI/messages only
    EMPLOYER_RESPONSE: "💬 Employer Response",
    SCREENING:         "🔎 Screening",
    INTERVIEW:         "🪑 Interview",
    ASSESSMENT:        "🧪 Assessment",
    ADDITIONAL_INFO:   "📄 Additional Info",
    OFFER:             "🎉 Offer",
    REJECTED:          "❌ Rejected",
    WITHDRAWN:         "↩️ Withdrawn",
    CLOSED:            "🗂️ Closed",
}

# ==============================================================================
# 2a. RECRUITER RESPONSE VOCABULARY
#     When the employer responds, the user records WHAT the response was
#     (outcome) and HOW it arrived (communication channel). An interview
#     request also asks for date/time + the manner of the interview.
# ==============================================================================
RESPONSE_REFUSED          = "REFUSED"
RESPONSE_INTERVIEW        = "INTERVIEW_REQUEST"
RESPONSE_ADDITIONAL_INFO  = "ADDITIONAL_INFO_REQUEST"

RESPONSE_TYPES = {
    RESPONSE_REFUSED:         "❌ Refused",
    RESPONSE_INTERVIEW:       "🗓️ Request for interview (date/time)",
    RESPONSE_ADDITIONAL_INFO: "📄 Request for additional data / file",
}

# Communication channels the recruiter may have used to reply (Enhancement #1).
RESPONSE_CHANNELS = ["Email", "WhatsApp", "Phone", "LinkedIn message", "Other"]

# Manner / tool used for the interview (Enhancement #2).
INTERVIEW_MODES = [
    "Online (video call)",
    "Skype",
    "Google Meet",
    "Microsoft Teams",
    "Zoom",
    "Phone call",
    "In person (on site)",
    "Other",
]

# ==============================================================================
# 2. LIFECYCLE TRANSITIONS
#    The system NEVER auto-advances. Every edge below is a MANUAL action that
#    the user explicitly performs. INTERVIEW -> INTERVIEW means "next round".
#
#    NOTE (Stage 3 spec): Follow-up is an ACTION, not a status.
#    WAITING is the resting state. Sending a follow-up keeps the status WAITING
#    and simply records the activity. Therefore FOLLOW_UP is NOT in this map as
#    a lifecycle status (it remains a constant for record/label compatibility).
# ==============================================================================
VALID_TRANSITIONS: Dict[str, List[str]] = {
    APPLIED:           [WAITING, EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    WAITING:           [EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    EMPLOYER_RESPONSE: [SCREENING, INTERVIEW, ASSESSMENT, ADDITIONAL_INFO, REJECTED, WITHDRAWN],
    SCREENING:         [INTERVIEW, ASSESSMENT, ADDITIONAL_INFO, REJECTED, WITHDRAWN],
    INTERVIEW:         [INTERVIEW, OFFER, REJECTED, WITHDRAWN],
    ASSESSMENT:        [INTERVIEW, OFFER, REJECTED, WITHDRAWN],
    ADDITIONAL_INFO:   [EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    OFFER:             [CLOSED],
    REJECTED:          [CLOSED],
    WITHDRAWN:         [CLOSED],
    CLOSED:            [],  # terminal – no further transitions
}
TERMINAL_OUTCOMES = {OFFER, REJECTED, WITHDRAWN, CLOSED}

# ==============================================================================
# 2b. CONFIGURATION  (Stage 2 — Waiting / Next-Action logic)
#     The follow-up interval is a CONFIG value, never hard-coded into the UI.
# ==============================================================================
# Rule 3 fallback: when no employer response date and no job closing date exists,
# the follow-up checkpoint is computed as application date + this interval.
# The V2 spec recommends a configurable default in the 7–14 calendar-day band.
FOLLOW_UP_INTERVAL_DAYS = 8  # calendar days (e.g. Applied 23 Aug -> next action 31 Aug)

# Label shown as the source of the computed checkpoint.
NEXT_ACTION_SOURCE_CONFIG = "follow_up (config fallback)"

# ==============================================================================
# 3. PERSISTENCE (mirrors services/profile_service.py)
#    Stored under data/users_db.json -> user_email -> "applications"
# ==============================================================================
USERS_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "users_db.json"


def _user_key() -> str:
    return st.session_state.get("user") or "CAND-UNKNOWN"


def _load_users_db() -> Dict[str, Any]:
    if USERS_DB_PATH.exists():
        try:
            return json.loads(USERS_DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_users_db(db: Dict[str, Any]) -> None:
    USERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_DB_PATH.write_text(
        json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _load_cache() -> Dict[str, Dict[str, Any]]:
    """Read this user's applications dict fresh from disk."""
    users_db = _load_users_db()
    user_data = users_db.get(_user_key(), {})
    return user_data.get("applications", {}) or {}


def _application_cache() -> Dict[str, Dict[str, Any]]:
    """
    In-memory cache lives in session_state for fast access during the run.
    Every mutation is also persisted to disk so records survive restarts.
    """
    if "applications" not in st.session_state:
        st.session_state.applications = _load_cache()
    return st.session_state.applications


def _persist() -> None:
    """Write the current session cache back to the per-user file."""
    cache = _application_cache()
    users_db = _load_users_db()
    user_data = users_db.setdefault(_user_key(), {})
    user_data["applications"] = {k: v for k, v in cache.items()}
    user_data["applications_updated_at"] = datetime.utcnow().isoformat()
    _save_users_db(users_db)


# ==============================================================================
# 4. TIME HELPERS
# ==============================================================================
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def add_business_days(start: Any, days: int = 5) -> str:
    """Return an ISO date `days` business days after `start` (skips Sat/Sun)."""
    d = _parse_date(start) or datetime.now().date()
    added = 0
    while added < days:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()


def _add_calendar_days(start: Any, days: int = 8) -> str:
    """Return an ISO date `days` calendar days after `start` (Stage 2 Rule 3)."""
    d = _parse_date(start) or datetime.now().date()
    return (d + timedelta(days=days)).isoformat()


def _extract_job_closing_date(job: Dict[str, Any]) -> str:
    """Best-effort read of a closing/apply-before date from the job snapshot."""
    if not job:
        return ""
    parsed = job.get("job_json") or {}
    candidate = (
        parsed.get("closing_date")
        or parsed.get("apply_before")
        or parsed.get("application_deadline")
        or job.get("closing_date")
        or job.get("application_deadline")
    )
    if not candidate:
        return ""
    try:
        d = _parse_date(candidate)
        return d.isoformat() if d else ""
    except Exception:
        return ""


def minutes_between(from_iso: Any, to_iso: Any) -> Optional[int]:
    """Whole minutes elapsed, or None if missing/invalid."""
    try:
        start = datetime.fromisoformat(str(from_iso))
        end = datetime.fromisoformat(str(to_iso))
        minutes = (end - start).total_seconds() / 60
        return max(0, int(round(minutes)))
    except (ValueError, TypeError):
        return None
# ==============================================================================
# 5. RECORD CREATION  (STAGE 1 — APPLIED)
# ==============================================================================
def create_application(
    job: Dict[str, Any],
    *,
    channel: str = "",
    application_date: Any = None,
    notes: str = "",
    recruiter: Optional[Dict[str, Any]] = None,
    docs: Optional[Dict[str, Any]] = None,
    docs_generated_at: Optional[str] = None,
    follow_up_days: Optional[int] = None,
    candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create and persist an Application Tracking Record after the user confirms
    that the application was actually submitted externally.

    Automatically captures (per the V2 spec 'Automatically recorded information'):
      job title, company, location, job URL, application source, CV version used,
      cover letter version used, recruiter contact, ATS/match score, and the
      initial follow-up checkpoint (Rule 3 fallback).

    The follow-up interval is a CONFIG value (FOLLOW_UP_INTERVAL_DAYS) unless the
    caller overrides it via follow_up_days — it is never hard-coded in the UI.
    """
    now = _now_iso()
    app_id = "APP-" + datetime.now().strftime("%Y%m%d-%H%M%S")

    company_id = job.get("company_id", "")
    company_name = job.get("company_name") or company_id or "—"
    if company_id and (company_name == "" or company_name == company_id):
        # Enrich with the company record when available.
        try:
            from utils.company import get_company
            comp = get_company(company_id)
            if comp and comp.get("name"):
                company_name = comp["name"]
        except Exception:
            pass

    app_date = _parse_date(application_date) or datetime.now().date()
    app_date_str = app_date.isoformat()

    # Time consumed = confirmation time - document generation time (Stage 1 spec)
    time_consumed_min = minutes_between(docs_generated_at, now)
    doc = docs or {}

    application = {
        "application_id": app_id,
        "job_id": job.get("job_id"),
        "candidate_id": candidate_id or st.session_state.get("candidate_id", "CAND-UNKNOWN"),
        "company_id": company_id,
        # Captured job snapshot (kept even if the job is later removed)
        "title": job.get("title", "Untitled Position"),
        "company_name": company_name,
        "location": job.get("location", ""),
        "country": job.get("country", ""),
        "job_url": job.get("job_url", ""),
        "source": job.get("source", ""),
        # Documents used
        "cv_version": doc.get("cv_path") or "",
        "cover_letter_version": doc.get("cover_letter_path") or "",
        "recruiter_email_path": doc.get("email_path") or "",
        # ATS snapshot at application time
        "ats_score": job.get("ats_score", 0),
        # Recruiter info (if already available)
        "recruiter_id": (recruiter or {}).get("contact_id", ""),
        "recruiter_name": (recruiter or {}).get("name", ""),
        "recruiter_email": (recruiter or {}).get("email", ""),
        # Submission metadata
        "status": APPLIED,
        "channel": channel,
        "application_date": app_date_str,
        "docs_generated_at": docs_generated_at or "",
        "time_consumed_min": time_consumed_min,
        "follow_up_checkpoint": _add_calendar_days(
            app_date_str, follow_up_days if follow_up_days is not None else FOLLOW_UP_INTERVAL_DAYS
        ),
        # Stage 2 — Waiting / monitoring context
        "employer_response_date": "",   # Rule 1: employer-provided response date (user may set)
        "job_closing_date": _extract_job_closing_date(job),  # Rule 2: information point only
        "next_action_source": "",        # which rule drove the current next action
        "last_activity": "Application submitted externally.",
        "last_activity_at": now,
        # Audit trail + future-stage collections
        "timeline": [
            {"status": APPLIED, "at": now, "note": notes or "Application submitted externally."}
        ],
        "recruiter_interactions": [],
        "interviews": [],
        "assessment": None,
        "outcome": None,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }

    cache = _application_cache()
    cache[app_id] = application
    _persist()
    return application


# ==============================================================================
# 6. READ HELPERS
# ==============================================================================
def get_all_applications(include_closed: bool = True) -> List[Dict[str, Any]]:
    """All application records, newest first."""
    apps = list(_application_cache().values())
    apps.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    if not include_closed:
        apps = [a for a in apps if a.get("status") != CLOSED]
    return apps


def get_active_applications() -> List[Dict[str, Any]]:
    return get_all_applications(include_closed=False)


def get_application(app_id: str) -> Optional[Dict[str, Any]]:
    return _application_cache().get(app_id)


def get_valid_transitions(status: str) -> List[str]:
    return list(VALID_TRANSITIONS.get(status, []))
# ==============================================================================
# 7. LIFECYCLE TRANSITION  (advance an application to a new status)
# ==============================================================================
def update_status(
    app_id: str,
    new_status: str,
    note: str = "",
    actor: str = "user",
) -> Optional[Dict[str, Any]]:
    """
    Manually advance an application to the given status. Validates the move
    against the lifecycle diagram: invalid transitions are rejected so the
    system can never corrupt the record.
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None

    current = app.get("status", APPLIED)
    allowed = get_valid_transitions(current)
    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition from {current} to {new_status}. "
            f"Allowed: {', '.join(allowed) or 'none'}"
        )

    now = _now_iso()
    app["status"] = new_status
    app["updated_at"] = now
    app["last_activity"] = f"Status changed to {STATUS_LABELS.get(new_status, new_status)}."
    app["last_activity_at"] = now
    app["timeline"].append({"status": new_status, "at": now, "note": note, "actor": actor})

    # Note when an interview / assessment is reached or a terminal outcome lands.
    if new_status == REJECTED:
        app["outcome"] = {"type": "rejected", "at": now, "note": note}
    elif new_status == OFFER:
        app["outcome"] = {"type": "offer", "at": now, "note": note}
    elif new_status == WITHDRAWN:
        app["outcome"] = {"type": "withdrawn", "at": now, "note": note}

    cache[app_id] = app
    _persist()
    return app


def close_application(app_id: str, note: str = "") -> Optional[Dict[str, Any]]:
    """Close a completed application. Records the final outcome for reporting."""
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    current = app.get("status")
    allowed = get_valid_transitions(current)
    if CLOSED not in allowed:
        return None  # only terminal outcomes (OFFER / REJECTED / WITHDRAWN) can be closed

    app["status"] = CLOSED
    app["updated_at"] = _now_iso()
    app["timeline"].append({"status": CLOSED, "at": _now_iso(), "note": note or "Application closed."})
    if app.get("outcome") is None:
        app["outcome"] = {"type": "closed", "at": _now_iso(), "note": note}
    cache[app_id] = app
    _persist()
    return app


# ==============================================================================
# 8. NEXT RECOMMENDED ACTION  (help the user know what to do next)
# ==============================================================================
def next_action(app: Dict[str, Any]) -> Dict[str, str]:
    """Return the recommended next action. For WAITING the decision is priority-aware.

    Rule 1 (employer response date) > Rule 2 (job closing date, info only) >
    Rule 3 (config follow-up checkpoint).
    """
    status = app.get("status", APPLIED)
    checkpoint = app.get("follow_up_checkpoint", "")
    resp_date = app.get("employer_response_date") or ""
    closing_date = app.get("job_closing_date") or ""

    if status == APPLIED:
        return {
            "action": "Monitor while waiting",
            "hint": f"Application submitted on {app.get('application_date')}. "
                    f"If you hear nothing by {checkpoint}, send a follow-up.",
            "date": checkpoint,
            "source": NEXT_ACTION_SOURCE_CONFIG,
        }
    if status == WAITING:
        if resp_date:
            return {
                "action": "Monitor until the employer response date",
                "hint": f"Employer said candidates will be contacted by {resp_date}. Monitor until then.",
                "date": resp_date,
                "source": "employer_response_date (Rule 1)",
            }
        if closing_date:
            return {
                "action": "Monitor past the job closing date",
                "hint": f"Job closing date: {closing_date} (information point). This is NOT the expected "
                        f"response date. If you hear nothing by your follow-up checkpoint ({checkpoint}), follow up.",
                "date": checkpoint,
                "source": "job_closing_date (Rule 2, info only)",
            }
        # Rule 3 fallback. If a follow-up was already sent, remind to keep waiting;
        # otherwise recommend sending one.
        if app.get("follow_ups"):
            return {
                "action": "Keep waiting for a response",
                "hint": f"Follow-up already sent. Next follow-up can be considered on/after {checkpoint} "
                        f"if there is still no employer response.",
                "date": checkpoint,
                "source": NEXT_ACTION_SOURCE_CONFIG,
            }
        return {
            "action": "Send / prepare a follow-up",
            "hint": f"No employer timeline given. Follow-up checkpoint: {checkpoint}.",
            "date": checkpoint,
            "source": NEXT_ACTION_SOURCE_CONFIG,
        }
    if status == EMPLOYER_RESPONSE:
        return {
            "action": "Log the recruiter response",
            "hint": "The employer responded — record what it was (refused / interview request / "
                    "additional info) and the channel it arrived on (Email, WhatsApp, Phone, ...).",
            "date": "",
            "source": "",
        }
    if status == SCREENING:
        return {
            "action": "Log the interview / assessment / rejection",
            "hint": "Screening done. Record the next step.",
            "date": "",
            "source": "",
        }
    if status == INTERVIEW:
        pending = _find_pending_interview(app)
        if pending:
            return {
                "action": "Schedule the requested interview",
                "hint": f"Round {pending['round']} was requested by the recruiter — add the "
                        f"date, time and manner (Online / Skype / Google Meet / Teams / ...).",
                "date": "",
                "source": "",
            }
        return {
            "action": "Log the next round or the outcome",
            "hint": "Add the next round, or record an offer / rejection / withdrawal.",
            "date": "",
            "source": "",
        }
    if status == ASSESSMENT:
        return {
            "action": "Log the assessment outcome",
            "hint": "Assessment done. Add the next round or the final outcome.",
            "date": "",
            "source": "",
        }
    if status == ADDITIONAL_INFO:
        return {
            "action": "Await the next employer response",
            "hint": "You supplied additional information. Wait for the employer's response.",
            "date": "",
            "source": "",
        }
    if status in (OFFER, REJECTED, WITHDRAWN):
        return {
            "action": "Close the application",
            "hint": f"Final outcome: {STATUS_LABELS.get(status, status)}. Close to finalize.",
            "date": "",
            "source": "",
        }
    if status == CLOSED:
        return {"action": "Done", "hint": "This application is closed.", "date": "", "source": ""}
    return {"action": "Continue tracking", "hint": "", "date": "", "source": ""}


def monitoring_context(app: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2 - Application Monitoring panel.

    Answers: "What is the current situation and what should I do next?"
    """
    na = next_action(app)
    today = datetime.now().date()

    app_date = _parse_date(app.get("application_date"))
    days_since = (today - app_date).days if app_date else None

    last_at = app.get("last_activity_at") or app.get("updated_at") or ""
    try:
        last_dt = datetime.fromisoformat(str(last_at))
    except (ValueError, TypeError):
        last_dt = None

    return {
        "status": app.get("status"),
        "status_label": STATUS_LABELS.get(app.get("status"), app.get("status")),
        "application_date": app.get("application_date", ""),
        "days_since_application": days_since,
        "last_activity": app.get("last_activity", "—"),
        "last_activity_at": last_dt.isoformat(timespec="minutes") if last_dt else "—",
        "next_action": na.get("action", ""),
        "next_action_date": na.get("date", "") or "",
        "next_action_source": na.get("source", "") or "",
        "recruiter_name": app.get("recruiter_name", ""),
        "recruiter_email": app.get("recruiter_email", ""),
        "cv_version": app.get("cv_version", ""),
        "cover_letter_version": app.get("cover_letter_version", ""),
        "job_closing_date": app.get("job_closing_date", ""),
        "employer_response_date": app.get("employer_response_date", ""),
        "last_response": app.get("last_response") or {},
        "responses_count": len(app.get("recruiter_responses", [])),
        "interviews_count": len(app.get("interviews", [])),
        "pending_interview": _find_pending_interview(app),
    }


def application_summary() -> Dict[str, int]:
    """Counts used by the Dashboard (Applied / Pending / Interview / Offers / Rejected)."""
    counts = {
        "applied": 0,
        "pending": 0,
        "interview": 0,
        "offers": 0,
        "rejected": 0,
        "total": 0,
    }
    for app in get_all_applications(include_closed=True):
        status = app.get("status")
        counts["total"] += 1
        if status == APPLIED:
            counts["applied"] += 1
        elif status in (WAITING, EMPLOYER_RESPONSE, SCREENING, ADDITIONAL_INFO):
            counts["pending"] += 1
        elif status in (INTERVIEW, ASSESSMENT):
            counts["interview"] += 1
        elif status == OFFER:
            counts["offers"] += 1
        elif status == REJECTED:
            counts["rejected"] += 1
    return counts
# ==============================================================================
# 9. RECORDING SUB-ACTIVITIES
#    These append to an application without changing its lifecycle STATUS.
#    (Stage 2 – FOLLOW-UP, Stage 3 – EMPLOYER RESPONSE, Stage 4 – INTERVIEW,
#     Stage 5 – ASSESSMENT, recruiter interaction log.)
# ==============================================================================
def record_follow_up(
    app_id: str,
    sent_at: Any = None,
    method: str = "Email",
    note: str = "",
    actor: str = "user",
) -> Optional[Dict[str, Any]]:
    """
    Stage 3 (reworked) — record a follow-up as an ACTION, not a status.

    Per the V2 spec, follow-up is NOT a lifecycle status. WAITING is the resting
    state; sending a follow-up keeps the application WAITING and simply records
    the communication in the follow_ups history + timeline.
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None

    current = app.get("status", APPLIED)
    if current != WAITING:
        raise ValueError(
            "A follow-up can only be sent while the application is in the WAITING state. "
            f"Current status: {STATUS_LABELS.get(current, current)}"
        )

    now = _now_iso()
    sent = _parse_date(sent_at) or datetime.now().date()
    app.setdefault("follow_ups", []).append({
        "at": now,
        "sent_date": sent.isoformat(),
        "method": method,
        "note": note,
        "event": "follow_up_sent",
    })

    # Status stays WAITING (action only) — but reflect it on the timeline.
    app["timeline"].append({
        "status": WAITING,
        "at": now,
        "note": note or f"Follow-up sent ({method}).",
        "actor": actor,
        "event": "follow_up_sent",
    })

    # Advance the follow-up checkpoint after each follow-up (gap before next nudge).
    app["follow_up_checkpoint"] = _add_calendar_days(now, FOLLOW_UP_INTERVAL_DAYS)

    app["updated_at"] = now
    app["last_activity"] = f"Follow-up sent on {sent.isoformat()} via {method}."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app


def follow_up_context(app: Dict[str, Any]) -> Dict[str, Any]:
    """Return follow-up timing context: checkpoint, days left / overdue flag."""
    checkpoint = app.get("follow_up_checkpoint", "")
    result = {"checkpoint": checkpoint, "days_left": None, "overdue": False}
    if not checkpoint:
        return result
    try:
        cp = datetime.fromisoformat(str(checkpoint)).date()
    except (ValueError, TypeError):
        return result
    today = datetime.now().date()
    days_left = (cp - today).days
    result["days_left"] = days_left
    result["overdue"] = days_left < 0
    return result
# ==============================================================================
# 8a. STAGE 3 — FOLLOW-UP as an ACTION (not a status)
#     A. Draft follow-up   B. Mark as contacted   C. Remind me later
# ==============================================================================
def follow_up_checkpoint_date(app: Dict[str, Any]) -> date:
    """Return the current follow-up checkpoint as a date object (or today)."""
    cp = app.get("follow_up_checkpoint", "")
    if cp:
        try:
            return datetime.fromisoformat(str(cp)).date()
        except (ValueError, TypeError):
            pass
    return datetime.now().date()


def draft_follow_up(app: Dict[str, Any]) -> Dict[str, str]:
    """
    Stage 3 A — generate a short follow-up message using:
    job title, company, application date, relevant candidate strengths,
    recruiter/contact info, previous communication.
    """
    strengths = app.get("ats_components") or {}
    candidate_strengths = ", ".join(list(strengths)[:3]) if strengths else "your relevant experience"

    prev_comm = ""
    follow_ups = app.get("follow_ups", [])
    if follow_ups:
        latest = follow_ups[-1]
        prev_comm = (f"Following up on my previous message sent "
                     f"{latest.get('sent_date', '')} via {latest.get('method', latest.get('channel', ''))}.")
    else:
        prev_comm = "I recently applied for this role."

    recruiter_line = ""
    if app.get("recruiter_name"):
        recruiter_line = f"Best regards to {app['recruiter_name']}."

    message = (
        f"Subject: Follow-up on {app.get('title', 'your')} application — {app.get('company_name', '')}\n\n"
        f"Hello,\n\n"
        f"{prev_comm} I remain very interested in the {app.get('title', 'position')} "
        f"role at {app.get('company_name', 'your company')} (application sent "
        f"{app.get('application_date', 'recently')}). I wanted to check whether any "
        f"additional information is needed from my side.\n\n"
        f"{recruiter_line}\n"
        f"I look forward to your response.\n\n"
        f"Best regards,\n"
        f"({app.get('candidate_id', '')})"
    )
    return {"message": message, "context": candidate_strengths}


def mark_contacted(
    app_id: str,
    contacted_at: Any = None,
    channel: str = "Email",
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Stage 3 B — user confirms the follow-up was sent externally.
    Records date, channel, contact, note. Status stays WAITING (action only).
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    if app.get("status") != WAITING:
        raise ValueError("Marking as contacted is only valid while the application is WAITING.")

    now = _now_iso()
    sent = _parse_date(contacted_at) or datetime.now().date()
    app.setdefault("follow_ups", []).append({
        "at": now,
        "sent_date": sent.isoformat(),
        "channel": channel,
        "method": channel,
        "note": note,
        "event": "contacted",
    })
    app["timeline"].append({
        "status": WAITING,
        "at": now,
        "note": note or f"Follow-up sent via {channel}.",
        "actor": "user",
        "event": "contacted",
    })
    app["follow_up_checkpoint"] = _add_calendar_days(now, FOLLOW_UP_INTERVAL_DAYS)
    app["updated_at"] = now
    app["last_activity"] = f"Contacted via {channel} on {sent.isoformat()}."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app


def remind_me_later(app_id: str, later_date: Any) -> Optional[Dict[str, Any]]:
    """Stage 3 C — the user chooses another date for the next follow-up reminder."""
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    d = _parse_date(later_date)
    if not d:
        raise ValueError("Please provide a valid reminder date.")
    now = _now_iso()
    app["follow_up_checkpoint"] = d.isoformat()
    app["timeline"].append({
        "status": WAITING,
        "at": now,
        "note": f"Follow-up reminder moved to {d.isoformat()}.",
        "actor": "user",
        "event": "remind_later",
    })
    app["updated_at"] = now
    app["last_activity"] = f"Reminder moved to {d.isoformat()}."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app



# ==============================================================================
# 8b. STAGE 2 — NEXT-ACTION RULE INPUTS  (Rule 1 / Rule 2)
# ==============================================================================
def set_employer_response_date(
    app_id: str,
    response_date: Any,
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Stage 2 Rule 1 - record an employer-provided response date.
    This becomes the PRIMARY next-action date (above job closing date & follow-up).
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    d = _parse_date(response_date)
    if not d:
        raise ValueError("Please provide a valid employer response date.")
    now = _now_iso()
    app["employer_response_date"] = d.isoformat()
    app["next_action_source"] = "employer_response_date (Rule 1)"
    app["timeline"].append({
        "status": app.get("status"),
        "at": now,
        "note": note or f"Employer indicated a response date: {d.isoformat()}.",
        "actor": "user",
        "event": "employer_response_date",
    })
    app["updated_at"] = now
    app["last_activity"] = f"Employer response date set to {d.isoformat()}."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app


def set_job_closing_date(
    app_id: str,
    closing_date: Any,
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Stage 2 Rule 2 - record the job closing date as an INFORMATION POINT.
    It is shown to the user but never auto-treated as the expected response date.
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    d = _parse_date(closing_date)
    if not d:
        raise ValueError("Please provide a valid job closing date.")
    now = _now_iso()
    app["job_closing_date"] = d.isoformat()
    app["last_activity"] = f"Job closing date set to {d.isoformat()} (information point)."
    app["last_activity_at"] = now
    app["updated_at"] = now
    cache[app_id] = app
    _persist()
    return app


def record_interaction(
    app_id: str,
    interaction_type: str,
    note: str = "",
    contact: str = "",
) -> Optional[Dict[str, Any]]:
    """Log a recruiter/employer interaction (email, call, message)."""
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    now = _now_iso()
    app.setdefault("recruiter_interactions", []).append({
        "at": now,
        "type": interaction_type,
        "contact": contact,
        "note": note,
        "actor": "user",
    })
    app["updated_at"] = now
    app["last_activity"] = f"Interaction logged: {interaction_type}."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app


def record_interview(
    app_id: str,
    round_no: int = 1,
    scheduled_at: Any = None,
    format: str = "Video Call",
    notes: str = "",
    mode: str = "",
) -> Optional[Dict[str, Any]]:
    """Add / update an interview round record. ``mode`` = manner (Skype, Meet, Teams...)."""
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    now = _now_iso()
    when = scheduled_at.isoformat() if isinstance(scheduled_at, (date, datetime)) else str(scheduled_at or "")
    interviews = app.setdefault("interviews", [])
    existing = next((iv for iv in interviews if iv.get("round") == round_no), None)
    if existing:
        existing.update({
            "scheduled_at": when or existing.get("scheduled_at", ""),
            "format": format,
            "mode": mode or existing.get("mode", ""),
            "notes": notes or existing.get("notes", ""),
            "updated_at": now,
        })
    else:
        interviews.append({
            "round": round_no,
            "scheduled_at": when,
            "format": format,
            "mode": mode,
            "notes": notes,
            "recorded_at": now,
        })
    app["updated_at"] = now
    app["last_activity"] = f"Interview round {round_no} recorded."
    app["last_activity_at"] = now
    cache[app_id] = app
    _persist()
    return app


def _find_pending_interview(app: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """First interview round that was requested but not yet scheduled (no date/time)."""
    for iv in app.get("interviews", []):
        if iv.get("requested") and not iv.get("scheduled_at"):
            return iv
    return None


def get_pending_interview(app: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Public helper: an interview round that still needs a date/time + manner."""
    return _find_pending_interview(app)

def record_employer_response(
    app_id: str,
    response_type: str,
    channel: str = "Email",
    responded_at: Any = None,
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Enhancement #1 — log a recruiter/employer response.

    The user records WHAT the response was (refused / interview request /
    additional-info request) and HOW it arrived (Email, WhatsApp, Phone, LinkedIn, ...).

    The lifecycle status automatically follows the outcome:
      REFUSED                   -> REJECTED
      INTERVIEW_REQUEST         -> INTERVIEW   (a pending interview round is added)
      ADDITIONAL_INFO_REQUEST   -> ADDITIONAL_INFO
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    if response_type not in RESPONSE_TYPES:
        raise ValueError(
            f"Unknown response type '{response_type}'. Choose one of: {', '.join(RESPONSE_TYPES)}."
        )
    if not channel:
        raise ValueError("Please provide the communication channel (Email, WhatsApp, Phone, ...).")

    current = app.get("status", APPLIED)
    now = _now_iso()
    responded = _parse_date(responded_at) or datetime.now().date()

    response_record = {
        "at": now,
        "responded_on": responded.isoformat(),
        "type": response_type,
        "type_label": RESPONSE_TYPES[response_type],
        "channel": channel,
        "note": note,
        "actor": "user",
    }
    app.setdefault("recruiter_responses", []).append(response_record)
    app.setdefault("recruiter_interactions", []).append({
        "at": now,
        "type": f"employer_response_{response_type.lower()}",
        "contact": channel,
        "note": note,
        "event": "employer_response",
    })

    # Map the outcome onto the lifecycle.
    if response_type == RESPONSE_REFUSED:
        new_status = REJECTED
    elif response_type == RESPONSE_ADDITIONAL_INFO:
        new_status = ADDITIONAL_INFO
    else:  # RESPONSE_INTERVIEW
        new_status = INTERVIEW

    allowed = get_valid_transitions(current)
    # A recruiter response is a real-world event that can reach any of the three
    # outcomes directly from the applied/waiting/employer-response states, even
    # though the generic status map is more conservative (e.g. ADDITIONAL_INFO is
    # not listed as a direct transition from APPLIED). We keep the generic
    # update_status() strict, but let the response recorder honour the outcome.
    if new_status not in allowed and current in (APPLIED, WAITING, EMPLOYER_RESPONSE):
        allowed = list(allowed) + [new_status]
    if new_status not in allowed:
        raise ValueError(
            f"Cannot log this response now: the application is "
            f"'{STATUS_LABELS.get(current, current)}' and "
            f"'{STATUS_LABELS.get(new_status, new_status)}' is not a valid next step. "
            f"Allowed: {', '.join(allowed) or 'none'}."
        )

    app["status"] = new_status
    app["last_response"] = response_record
    app["updated_at"] = now
    action_desc = f"Recruiter response logged: {RESPONSE_TYPES[response_type]} via {channel}."
    app["last_activity"] = action_desc
    app["last_activity_at"] = now
    app["timeline"].append({
        "status": new_status,
        "at": now,
        "note": note or action_desc,
        "actor": "user",
        "event": f"employer_response_{response_type.lower()}",
    })

    if new_status == REJECTED:
        app["outcome"] = {"type": "rejected", "at": now, "note": note}
    elif new_status == INTERVIEW and response_type == RESPONSE_INTERVIEW:
        # Enhancement #2 — create a pending round so the UI asks for date/time/manner.
        round_no = max([iv.get("round", 0) for iv in app.get("interviews", [])], default=0) + 1
        app.setdefault("interviews", []).append({
            "round": round_no,
            "scheduled_at": "",
            "format": "",
            "mode": "",
            "manner": "",
            "notes": note or "Recruiter requested the interview.",
            "requested": True,
            "recorded_at": now,
        })

    cache[app_id] = app
    _persist()
    return app


def schedule_interview(
    app_id: str,
    round_no: int,
    scheduled_at: Any = None,
    mode: str = "Online (video call)",
    notes: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Enhancement #2 — save the confirmed interview date + time and the manner
    (online, Skype, Google Meet, Teams, Zoom, phone, on-site, ...).
    """
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    if not scheduled_at:
        raise ValueError("Please provide the interview date and time.")
    now = _now_iso()
    when = scheduled_at.isoformat() if isinstance(scheduled_at, (date, datetime)) else str(scheduled_at)
    interviews = app.setdefault("interviews", [])
    existing = next((iv for iv in interviews if iv.get("round") == round_no), None)
    if existing:
        existing.update({
            "scheduled_at": when,
            "mode": mode,
            "manner": mode,
            "format": mode,
            "notes": notes or existing.get("notes", ""),
            "requested": False,
            "updated_at": now,
        })
    else:
        interviews.append({
            "round": round_no,
            "scheduled_at": when,
            "mode": mode,
            "manner": mode,
            "format": mode,
            "notes": notes,
            "requested": False,
            "recorded_at": now,
        })
    app["updated_at"] = now
    app["last_activity"] = f"Interview round {round_no} scheduled: {when} ({mode})."
    app["last_activity_at"] = now
    app["timeline"].append({
        "status": app.get("status", INTERVIEW),
        "at": now,
        "note": f"Interview round {round_no} scheduled on {when} — {mode}.",
        "actor": "user",
        "event": "interview_scheduled",
    })
    cache[app_id] = app
    _persist()
    return app

def record_assessment(
    app_id: str,
    completed_at: Any = None,
    type: str = "",
    score: str = "",
    note: str = "",
) -> Optional[Dict[str, Any]]:
    """Record an assessment result."""
    cache = _application_cache()
    app = cache.get(app_id)
    if not app:
        return None
    now = _now_iso()
    app["assessment"] = {
        "completed_at": str(completed_at or _parse_date(now) or ""),
        "type": type,
        "score": score,
        "note": note,
        "recorded_at": now,
    }
    app["updated_at"] = now
    cache[app_id] = app
    _persist()
    return app