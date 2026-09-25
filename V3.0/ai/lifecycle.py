"""AIROS V3 - Application lifecycle (CHG-018).

Deterministic port of the V2 ``app/utils/tracker.py`` logic (the full
post-application workflow), with ALL persistence removed:

- V2 persisted per-user into ``data/users_db.json``; in V3 the record lives
  in the caller's own ``applications`` row (Supabase, RLS via the caller's
  token) and the FastAPI router applies these pure functions to it.
- V2 injected ``st.session_state`` / ``st.error``; here every failure is a
  raised :class:`TransitionError` (or ValueError for bad input) with a
  user-displayable message.

The tracker is intentionally MANUAL and CONSERVATIVE (V2 spec):
- AIROS never assumes an application has progressed unless the user confirms.
- Every lifecycle transition requires an explicit user action.
- No application is forced through every stage (APPLIED -> INTERVIEW -> OFFER
  is valid; APPLIED -> REJECTED is also valid).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# ==============================================================================
# 1. STATUS VOCABULARY (V2 verbatim)
# ==============================================================================
APPLIED = "APPLIED"
WAITING = "WAITING"
FOLLOW_UP = "FOLLOW_UP"  # an ACTION, not a lifecycle status (kept for compatibility)
EMPLOYER_RESPONSE = "EMPLOYER_RESPONSE"
SCREENING = "SCREENING"
INTERVIEW = "INTERVIEW"
ASSESSMENT = "ASSESSMENT"
ADDITIONAL_INFO = "ADDITIONAL_INFO"
OFFER = "OFFER"
REJECTED = "REJECTED"
WITHDRAWN = "WITHDRAWN"
CLOSED = "CLOSED"

STATUS_LABELS = {
    APPLIED: "📥 Applied",
    WAITING: "⏳ Waiting",
    FOLLOW_UP: "📤 Follow-up (action)",
    EMPLOYER_RESPONSE: "💬 Employer Response",
    SCREENING: "🔎 Screening",
    INTERVIEW: "🪑 Interview",
    ASSESSMENT: "🧪 Assessment",
    ADDITIONAL_INFO: "📄 Additional Info",
    OFFER: "🎉 Offer",
    REJECTED: "❌ Rejected",
    WITHDRAWN: "↩️ Withdrawn",
    CLOSED: "🗂️ Closed",
}

# ==============================================================================
# 1a. RECRUITER RESPONSE VOCABULARY (V2 verbatim)
# ==============================================================================
RESPONSE_REFUSED = "REFUSED"
RESPONSE_INTERVIEW = "INTERVIEW_REQUEST"
RESPONSE_ADDITIONAL_INFO = "ADDITIONAL_INFO_REQUEST"

RESPONSE_TYPES = {
    RESPONSE_REFUSED: "❌ Refused",
    RESPONSE_INTERVIEW: "🗓️ Request for interview (date/time)",
    RESPONSE_ADDITIONAL_INFO: "📄 Request for additional data / file",
}

RESPONSE_CHANNELS = ["Email", "WhatsApp", "Phone", "LinkedIn message", "Other"]

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
# 2. LIFECYCLE TRANSITIONS (V2 verbatim; manual-only, never auto-advanced)
# ==============================================================================
VALID_TRANSITIONS: Dict[str, List[str]] = {
    APPLIED: [WAITING, EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    WAITING: [EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    EMPLOYER_RESPONSE: [SCREENING, INTERVIEW, ASSESSMENT, ADDITIONAL_INFO, REJECTED, WITHDRAWN],
    SCREENING: [INTERVIEW, ASSESSMENT, ADDITIONAL_INFO, REJECTED, WITHDRAWN],
    INTERVIEW: [INTERVIEW, OFFER, REJECTED, WITHDRAWN],
    ASSESSMENT: [INTERVIEW, OFFER, REJECTED, WITHDRAWN],
    ADDITIONAL_INFO: [EMPLOYER_RESPONSE, INTERVIEW, ASSESSMENT, REJECTED, WITHDRAWN],
    OFFER: [CLOSED],
    REJECTED: [CLOSED],
    WITHDRAWN: [CLOSED],
    CLOSED: [],  # terminal
}
TERMINAL_OUTCOMES = {OFFER, REJECTED, WITHDRAWN, CLOSED}

# Rule 3 fallback: application date + this interval (V2 config, 7-14 band).
FOLLOW_UP_INTERVAL_DAYS = 8  # calendar days
NEXT_ACTION_SOURCE_CONFIG = "follow_up (config fallback)"


class TransitionError(ValueError):
    """A lifecycle move is invalid (user-displayable, deterministic)."""


# ==============================================================================
# 3. TIME HELPERS (V2 verbatim)
# ==============================================================================
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def add_calendar_days(start: Any, days: int = 8) -> str:
    d = parse_date(start) or datetime.now().date()
    return (d + timedelta(days=days)).isoformat()


def add_business_days(start: Any, days: int = 5) -> str:
    d = parse_date(start) or datetime.now().date()
    added = 0
    while added < days:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()


def minutes_between(from_iso: Any, to_iso: Any) -> Optional[int]:
    try:
        start = datetime.fromisoformat(str(from_iso))
        end = datetime.fromisoformat(str(to_iso))
        return max(0, int(round((end - start).total_seconds() / 60)))
    except (ValueError, TypeError):
        return None


def extract_job_closing_date(job: Dict[str, Any]) -> str:
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
    d = parse_date(candidate)
    return d.isoformat() if d else ""


# ==============================================================================
# 4. IDENTIFIERS (V2 ids.py parity, deterministic per-account sequence)
# ==============================================================================
def next_sequential_id(prefix: str, existing_ids: List[str]) -> str:
    """``JOB-2026-000123`` style ID: max existing per-account sequence + 1."""
    year = datetime.now().year
    tag = f"{prefix}-{year}-"
    seq = 0
    for raw in existing_ids:
        value = str(raw)
        if value.startswith(tag):
            try:
                seq = max(seq, int(value[len(tag):]))
            except ValueError:
                continue
    return f"{prefix}-{year}-{seq + 1:06d}"


# ==============================================================================
# 5. RECORD CREATION (Stage 1 - APPLIED; V2 create_application verbatim)
# ==============================================================================
def create_application_record(
    application_id: str,
    job: Dict[str, Any],
    *,
    company_name: str = "",
    channel: str = "",
    application_date: Any = None,
    notes: str = "",
    recruiter: Optional[Dict[str, Any]] = None,
    docs: Optional[Dict[str, Any]] = None,
    docs_generated_at: Optional[str] = None,
    docs_approved_at: Optional[str] = None,
    follow_up_days: Optional[int] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the V2-shaped tracking record (status APPLIED)."""
    now = now or now_iso()
    app_date = parse_date(application_date) or datetime.now().date()
    app_date_str = app_date.isoformat()
    time_consumed_min = minutes_between(docs_generated_at, now)
    doc = docs or {}
    recruiter = recruiter or {}

    # Recruiter audit trail: capture the initial recruiter snapshot at record
    # creation so recruiter_interactions is never silently empty even when the
    # user goes straight from documents to confirm (CHG-023 hardening).
    initial_interactions: List[Dict[str, Any]] = []
    if any(recruiter.get(k) for k in ("contact_id", "name", "email", "position", "linkedin_url")):
        initial_interactions.append({
            "at": now,
            "type": "recruiter_contact_initial",
            "event": "application_created",
            "contact_id": recruiter.get("contact_id", ""),
            "name": recruiter.get("name", ""),
            "email": recruiter.get("email", ""),
            "position": recruiter.get("position", ""),
            "linkedin_url": recruiter.get("linkedin_url", ""),
            "phone": recruiter.get("phone", ""),
        })

    return {
        "application_id": application_id,
        "job_id": job.get("job_id", ""),
        "company_id": job.get("company_id", ""),
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
        "recruiter_id": recruiter.get("contact_id", ""),
        "recruiter_name": recruiter.get("name", ""),
        "recruiter_email": recruiter.get("email", ""),
        # Submission metadata
        "status": APPLIED,
        "channel": channel,
        "application_date": app_date_str,
        "docs_generated_at": docs_generated_at or "",
        "time_consumed_min": time_consumed_min,
        "follow_up_checkpoint": add_calendar_days(
            app_date_str, follow_up_days if follow_up_days is not None else FOLLOW_UP_INTERVAL_DAYS
        ),
        # Stage 2 - Waiting / monitoring context
        "employer_response_date": "",   # Rule 1 (user may set)
        "job_closing_date": extract_job_closing_date(job),  # Rule 2 (info only)
        "next_action_source": "",
        "last_activity": "Application submitted externally.",
        "last_activity_at": now,
        # Audit trail + stage collections
        "timeline": [
            {"status": APPLIED, "at": now, "note": notes or "Application submitted externally."}
        ],
        "recruiter_interactions": initial_interactions,
        "recruiter_responses": [],
        "follow_ups": [],
        "interviews": [],
        "assessment": None,
        "outcome": "",
        "outcome_detail": None,
        "notes": notes,
        "docs_approved_at": docs_approved_at or "",
        "created_at": now,
        "updated_at": now,
    }


# ==============================================================================
# 6. LIFECYCLE TRANSITION (manual only; V2 update_status verbatim logic)
# ==============================================================================
def get_valid_transitions(status: str) -> List[str]:
    return list(VALID_TRANSITIONS.get(status, []))


def update_status_record(
    app: Dict[str, Any],
    new_status: str,
    note: str = "",
    actor: str = "user",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Manually advance an application; invalid moves raise TransitionError."""
    current = app.get("status", APPLIED)
    allowed = get_valid_transitions(current)
    if new_status not in allowed:
        raise TransitionError(
            f"Invalid transition from {current} to {new_status}. "
            f"Allowed: {', '.join(allowed) or 'none'}"
        )
    now = now or now_iso()
    app["status"] = new_status
    app["updated_at"] = now
    app["last_activity"] = f"Status changed to {STATUS_LABELS.get(new_status, new_status)}."
    app["last_activity_at"] = now
    app.setdefault("timeline", []).append(
        {"status": new_status, "at": now, "note": note, "actor": actor}
    )
    if new_status == REJECTED:
        app["outcome"] = "rejected"
        app["outcome_detail"] = {"type": "rejected", "at": now, "note": note}
    elif new_status == OFFER:
        app["outcome"] = "offer"
        app["outcome_detail"] = {"type": "offer", "at": now, "note": note}
    elif new_status == WITHDRAWN:
        app["outcome"] = "withdrawn"
        app["outcome_detail"] = {"type": "withdrawn", "at": now, "note": note}
    return app


def close_application_record(
    app: Dict[str, Any], note: str = "", now: Optional[str] = None
) -> Dict[str, Any]:
    """Close a completed application (only from terminal outcomes)."""
    current = app.get("status", APPLIED)
    if CLOSED not in get_valid_transitions(current):
        raise TransitionError(
            "Only final outcomes (Offer / Rejected / Withdrawn) can be closed."
        )
    now = now or now_iso()
    app["status"] = CLOSED
    app["updated_at"] = now
    app.setdefault("timeline", []).append(
        {"status": CLOSED, "at": now, "note": note or "Application closed."}
    )
    if not app.get("outcome"):
        app["outcome"] = "closed"
        app["outcome_detail"] = {"type": "closed", "at": now, "note": note}
    return app


# ==============================================================================
# 7. STAGE 3 - FOLLOW-UP as an ACTION (not a status; V2 verbatim logic)
# ==============================================================================
def draft_follow_up(app: Dict[str, Any]) -> Dict[str, str]:
    """Deterministic follow-up draft (V2 draft_follow_up parity)."""
    strengths = app.get("ats_components") or {}
    candidate_strengths = ", ".join(list(strengths)[:3]) if strengths else "your relevant experience"

    follow_ups = app.get("follow_ups") or []
    if follow_ups:
        latest = follow_ups[-1]
        prev_comm = (
            f"Following up on my previous message sent "
            f"{latest.get('sent_date', '')} via {latest.get('method', latest.get('channel', ''))}."
        )
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


def mark_contacted_record(
    app: Dict[str, Any],
    contacted_at: Any = None,
    channel: str = "Email",
    note: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """User confirms the follow-up was sent externally. Status stays WAITING."""
    if app.get("status") != WAITING:
        raise TransitionError("Marking as contacted is only valid while the application is WAITING.")
    now = now or now_iso()
    sent = parse_date(contacted_at) or datetime.now().date()
    app.setdefault("follow_ups", []).append({
        "at": now,
        "sent_date": sent.isoformat(),
        "channel": channel,
        "method": channel,
        "note": note,
        "event": "contacted",
    })
    app.setdefault("timeline", []).append({
        "status": WAITING,
        "at": now,
        "note": note or f"Follow-up sent via {channel}.",
        "actor": "user",
        "event": "contacted",
    })
    app["follow_up_checkpoint"] = add_calendar_days(now, FOLLOW_UP_INTERVAL_DAYS)
    app["updated_at"] = now
    app["last_activity"] = f"Contacted via {channel} on {sent.isoformat()}."
    app["last_activity_at"] = now
    return app


def remind_me_later_record(
    app: Dict[str, Any], days: int = FOLLOW_UP_INTERVAL_DAYS, now: Optional[str] = None
) -> Dict[str, Any]:
    """Push the follow-up checkpoint by N calendar days (default the config)."""
    now = now or now_iso()
    days = int(days) if days and int(days) > 0 else FOLLOW_UP_INTERVAL_DAYS
    app["follow_up_checkpoint"] = add_calendar_days(now, days)
    app["updated_at"] = now
    app["last_activity"] = f"Reminder postponed by {days} days (new checkpoint {app['follow_up_checkpoint']})."
    app["last_activity_at"] = now
    return app


def set_employer_response_date_record(
    app: Dict[str, Any], response_date: Any, now: Optional[str] = None
) -> Dict[str, Any]:
    """Stage 2 Rule 1 - the employer-provided response date (user may set)."""
    d = parse_date(response_date)
    if not d:
        raise ValueError("Please provide a valid employer response date.")
    now = now or now_iso()
    app["employer_response_date"] = d.isoformat()
    app["next_action_source"] = "employer_response_date"
    app["updated_at"] = now
    app["last_activity"] = f"Employer response date set to {d.isoformat()}."
    app["last_activity_at"] = now
    return app


def set_job_closing_date_record(
    app: Dict[str, Any], closing_date: Any, now: Optional[str] = None
) -> Dict[str, Any]:
    """Stage 2 Rule 2 - job closing date as an INFORMATION POINT only."""
    d = parse_date(closing_date)
    if not d:
        raise ValueError("Please provide a valid job closing date.")
    now = now or now_iso()
    app["job_closing_date"] = d.isoformat()
    app["updated_at"] = now
    app["last_activity"] = f"Job closing date set to {d.isoformat()} (information point)."
    app["last_activity_at"] = now
    return app


def record_interaction_record(
    app: Dict[str, Any],
    interaction_type: str,
    note: str = "",
    contact: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Log a recruiter/employer interaction (email, call, message)."""
    now = now or now_iso()
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
    return app


# ==============================================================================
# 8. RECRUITER RESPONSE (V2 record_employer_response verbatim logic)
# ==============================================================================
def response_target_status(response_type: str) -> str:
    """Outcome -> lifecycle status (V2 mapping)."""
    if response_type == RESPONSE_REFUSED:
        return REJECTED
    if response_type == RESPONSE_ADDITIONAL_INFO:
        return ADDITIONAL_INFO
    if response_type == RESPONSE_INTERVIEW:
        return INTERVIEW
    raise ValueError(
        f"Unknown response type '{response_type}'. Choose one of: {', '.join(RESPONSE_TYPES)}."
    )


def record_employer_response_record(
    app: Dict[str, Any],
    response_type: str,
    channel: str = "Email",
    responded_on: Any = None,
    note: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Log WHAT the response was + HOW it arrived; the status follows the outcome."""
    if response_type not in RESPONSE_TYPES:
        raise ValueError(
            f"Unknown response type '{response_type}'. Choose one of: {', '.join(RESPONSE_TYPES)}."
        )
    if not channel:
        raise ValueError("Please provide the communication channel (Email, WhatsApp, Phone, ...).")

    current = app.get("status", APPLIED)
    now = now or now_iso()
    responded = parse_date(responded_on) or datetime.now().date()

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

    new_status = response_target_status(response_type)
    allowed = get_valid_transitions(current)
    # A recruiter response is a real-world event that can reach any of the three
    # outcomes directly from the applied/waiting/employer-response states (V2).
    if new_status not in allowed and current in (APPLIED, WAITING, EMPLOYER_RESPONSE):
        allowed = list(allowed) + [new_status]
    if new_status not in allowed:
        raise TransitionError(
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
    app.setdefault("timeline", []).append({
        "status": new_status,
        "at": now,
        "note": note or action_desc,
        "actor": "user",
        "event": f"employer_response_{response_type.lower()}",
    })

    if new_status == REJECTED:
        app["outcome"] = "rejected"
        app["outcome_detail"] = {"type": "rejected", "at": now, "note": note}
    elif new_status == INTERVIEW and response_type == RESPONSE_INTERVIEW:
        # Enhancement #2 - create a pending round so the UI asks for date/time/manner.
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
    return app


# ==============================================================================
# 9. INTERVIEWS + ASSESSMENT (V2 verbatim logic)
# ==============================================================================
def find_pending_interview(app: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """First interview round requested but not yet scheduled (no date/time)."""
    for iv in app.get("interviews", []) or []:
        if iv.get("requested") and not iv.get("scheduled_at"):
            return iv
    return None


def schedule_interview_record(
    app: Dict[str, Any],
    round_no: int,
    scheduled_at: Any = None,
    mode: str = "Online (video call)",
    notes: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Save the confirmed interview date/time + manner (V2 schedule_interview)."""
    if not scheduled_at:
        raise ValueError("Please provide the interview date and time.")
    now = now or now_iso()
    when = scheduled_at if isinstance(scheduled_at, str) else str(scheduled_at)
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
    app.setdefault("timeline", []).append({
        "status": app.get("status", INTERVIEW),
        "at": now,
        "note": f"Interview round {round_no} scheduled on {when} — {mode}.",
        "actor": "user",
        "event": "interview_scheduled",
    })
    return app


def record_assessment_record(
    app: Dict[str, Any],
    completed_at: Any = None,
    type: str = "",
    score: str = "",
    note: str = "",
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an assessment result (V2 record_assessment)."""
    now = now or now_iso()
    app["assessment"] = {
        "completed_at": str(parse_date(completed_at) or ""),
        "type": type,
        "score": score,
        "note": note,
        "recorded_at": now,
    }
    app["updated_at"] = now
    app["last_activity"] = "Assessment result recorded."
    app["last_activity_at"] = now
    return app


# ==============================================================================
# 10. NEXT RECOMMENDED ACTION (V2 next_action verbatim logic)
# ==============================================================================
def next_action(app: Dict[str, Any]) -> Dict[str, str]:
    """Recommended next action. WAITING is priority-aware:

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
        pending = find_pending_interview(app)
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
    return {
        "action": "Archived",
        "hint": "This application is closed and kept for reporting.",
        "date": "",
        "source": "",
    }



