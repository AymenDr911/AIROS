# app/pages/5_Job_Tracking.py
"""
AIROS V2 — Post-Application Job Tracking (Stage 1 + lifecycle shell)
=====================================================================
This page is the user's command centre for tracking submitted applications.

Stage 1 — Applied
  - Confirms and records that an application was submitted.
  - Displays the Application Submitted card (company, job title, application
    date, application channel, CV used, time consumed, current status).
  - Primary action: View Application
  - Secondary action: Update Status

Only MANUAL transitions are offered (per the lifecycle spec). The system never
auto-advances an application.
"""
import sys
from pathlib import Path
from datetime import datetime

app_dir = Path(__file__).resolve().parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

import streamlit as st

from utils.tracker import (
    APPLIED,
    WAITING,
    FOLLOW_UP,  # kept for compatibility — follow-up is an ACTION, not a lifecycle status
    EMPLOYER_RESPONSE,
    SCREENING,
    INTERVIEW,
    ASSESSMENT,
    ADDITIONAL_INFO,
    OFFER,
    REJECTED,
    WITHDRAWN,
    CLOSED,
    STATUS_LABELS,
    get_active_applications,
    get_all_applications,
    get_application,
    get_valid_transitions,
    update_status,
    close_application,
    next_action,
    record_follow_up,
    follow_up_context,
    monitoring_context,
    set_employer_response_date,
    set_job_closing_date,
    draft_follow_up,
    mark_contacted,
    remind_me_later,
    follow_up_checkpoint_date,
    RESPONSE_REFUSED,
    RESPONSE_INTERVIEW,
    RESPONSE_ADDITIONAL_INFO,
    RESPONSE_TYPES,
    RESPONSE_CHANNELS,
    INTERVIEW_MODES,
    record_employer_response,
    schedule_interview,
    get_pending_interview,
)

st.set_page_config(page_title="Job Tracking", page_icon="📡", layout="wide")
st.title("📡 Job Tracking")
st.caption("Final stage: monitor submitted applications, log progress, and record the final outcome. Nothing progresses unless you confirm it.")

active = get_active_applications()

# ──────────────────────────────────────────────
# Summary metrics
# ──────────────────────────────────────────────
if active:
    sums = {"APPLIED": 0, "WAITING": 0, "FOLLOW_UP": 0, "EMPLOYER_RESPONSE": 0,
            "SCREENING": 0, "INTERVIEW": 0, "ASSESSMENT": 0, "ADDITIONAL_INFO": 0,
            "OFFER": 0, "REJECTED": 0, "WITHDRAWN": 0}
    for a in active:
        s = a.get("status")
        sums[s] = sums.get(s, 0) + 1

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📥 Applied", sums["APPLIED"])
    m2.metric("⏳ Waiting", sums["WAITING"] + sums["FOLLOW_UP"])
    m3.metric("🪑 Interviews", sums["INTERVIEW"] + sums["ASSESSMENT"])
    m4.metric("🎉 Offers", sums["OFFER"])
    m5.metric("❌ Rejected", sums["REJECTED"])
    st.markdown("---")
else:
    st.info("No active applications yet.")
    st.caption("Go to **Job Application** → confirm an application as **Sent successfully** to create your first tracking record.")
    st.stop()

# ──────────────────────────────────────────────
# Select an application to open
# ──────────────────────────────────────────────
app_options = {
    f"{STATUS_LABELS.get(a.get('status'), a.get('status'))} · {a.get('title', 'Untitled')} · {a.get('company_name', '')} ({a.get('application_id')})": a["application_id"]
    for a in active
}

selected_label = st.selectbox(
    "Your active applications",
    options=list(app_options.keys()),
    key="track_selected_app",
)
selected_app_id = app_options[selected_label]
app = get_application(selected_app_id)

if not app:
    st.error("Selected application not found.")
    st.stop()

# ──────────────────────────────────────────────
# PERSPECTIVE ON THE APPLICATION  (Stage 1 detailed view)
# ──────────────────────────────────────────────
st.subheader("Application Submitted")
current_status = app.get("status", "APPLIED")

with st.container(border=True):
    c1, c2 = st.columns(2)
    c1.markdown(f"**Company**  \n{app.get('company_name', '—')}")
    c1.markdown(f"**Job Title**  \n{app.get('title', '—')}")
    c1.markdown(f"**Application Date**  \n{app.get('application_date', '—')}")
    c1.markdown(f"**Application Channel**  \n{app.get('channel', '—') or '—'}")

    c2.markdown(f"**Current Status**  \n{STATUS_LABELS.get(current_status, current_status)}")
    c2.markdown(f"**ATS Score**  \n{app.get('ats_score', 0)}%")
    c2.markdown(f"**Location**  \n{app.get('location', '—')}")
    c2.markdown("**Application Source**  \n" + (app.get("source") or "—"))

st.markdown("### 📄 Versions used & time consumed")
v1, v2, v3 = st.columns(3)
with v1:
    st.markdown(f"**Tailored CV**  \n`{app.get('cv_version') or '—'}`")
with v2:
    st.markdown(f"**Cover Letter**  \n`{app.get('cover_letter_version') or '—'}`")
with v3:
    t = app.get("time_consumed_min")
    st.markdown(f"**Time Consumed (min)**  \n{t if t is not None else '—'}")

recruiter = app.get("recruiter_name") or ""
recruiter_email = app.get("recruiter_email") or ""
if recruiter or recruiter_email:
    st.markdown(f"**Recruiter**  \n{recruiter or '—'} ({recruiter_email})")
last_resp = app.get("last_response")
if last_resp:
    st.markdown(
        f"**Last recruiter response**  \n{last_resp.get('type_label', last_resp.get('type'))} "
        f"· via {last_resp.get('channel', '—')} · {last_resp.get('responded_on', '')}"
    )

# ──────────────────────────────────────────────
# STAGE 2 — APPLICATION MONITORING PANEL
#     "What is the current situation and what should I do next?"
# ──────────────────────────────────────────────
st.markdown("## 📡 Monitoring")
mc = monitoring_context(app)

mon_cols = st.columns(4)
mon_cols[0].metric("Status", mc["status_label"])
mon_cols[0].caption("Current status")
mon_cols[1].metric("Applied", mc["application_date"])
mon_cols[1].caption("Application date")
mon_cols[2].metric(
    "Days since",
    mc["days_since_application"] if mc["days_since_application"] is not None else "—",
)
mon_cols[2].caption("Days since application")
mon_cols[3].metric(
    "Next action date",
    mc["next_action_date"] or "—",
)
mc_next = mc["next_action"] or "—"

with st.container(border=True):
    st.markdown(f"**Current status:** {mc['status_label']}  ·  **Next action:** {mc_next}")
    st.markdown(f"- **Days since application:** {mc['days_since_application'] if mc['days_since_application'] is not None else '—'}")
    st.markdown(f"- **Last activity:** {mc['last_activity']} ({mc['last_activity_at']})")
    st.markdown(f"- **Next recommended action:** {mc['next_action']}")
    if mc["next_action_date"]:
        st.markdown(f"- **Next action date:** {mc['next_action_date']}  *({mc['next_action_source'] or 'source unknown'})*")
    if mc["recruiter_name"] or mc["recruiter_email"]:
        st.markdown(f"- **Recruiter:** {mc['recruiter_name']} ({mc['recruiter_email']})")
    if mc["cv_version"] or mc["cover_letter_version"]:
        st.markdown(f"- **Documents:** CV `{mc['cv_version'] or '—'}`, Cover `{mc['cover_letter_version'] or '—'}`")
    if mc["job_closing_date"]:
        st.caption(f"Job closing date (info only): {mc['job_closing_date']}")
    if mc["employer_response_date"]:
        st.caption(f"Employer response date: {mc['employer_response_date']}")

# ── Stage 2 Rule 1 / Rule 2 inputs (only relevant while in play) ──
rule_show = len([x for x in (app.get("employer_response_date"), app.get("job_closing_date")) if x])
if current_status in (WAITING, APPLIED, FOLLOW_UP):
    with st.expander("⚙️ Set employer response date / job closing date (Next-Action rules)", expanded=rule_show > 0):
        r1, r2 = st.columns(2)
        with r1:
            with st.form("set_resp_date_form"):
                resp_date = st.date_input("Employer response date (Rule 1)", value=datetime.now().date())
                resp_note = st.text_input("Note (optional)")
                if st.form_submit_button("Set Response Date"):
                    try:
                        set_employer_response_date(selected_app_id, resp_date, resp_note)
                        st.success("Employer response date saved.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        with r2:
            with st.form("set_closing_date_form"):
                close_date = st.date_input("Job closing date (Rule 2 – info)", value=datetime.now().date())
                if st.form_submit_button("Set Closing Date"):
                    try:
                        set_job_closing_date(selected_app_id, close_date)
                        st.success("Job closing date saved (information point).")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

st.markdown("---")

# ──────────────────────────────────────────────
# Next recommended action
# ──────────────────────────────────────────────
na = next_action(app)
with st.container(border=True):
    st.markdown(f"**Next recommended action:** {na['action']}")
    st.caption(na["hint"])

# ──────────────────────────────────────────────
# STAGE 3 — RECRUITER RESPONSE (Enhancement #1)
#     The employer replied — capture what the response was (refused /
#     interview request / additional info) and the channel it came on.
#     An interview request additionally asks for date + time + manner.
# ──────────────────────────────────────────────
response_eligible = current_status in (APPLIED, WAITING, EMPLOYER_RESPONSE,
                                       ADDITIONAL_INFO, SCREENING, INTERVIEW)
has_response = bool(app.get("recruiter_responses"))

if current_status == EMPLOYER_RESPONSE and not has_response:
    st.warning(
        "⚠️ You recorded that the employer responded — please log the outcome below "
        "(refused, interview request, or additional-info request) and the channel it arrived on."
    )

if response_eligible:
    st.markdown("## 💬 Recruiter Response")
    st.caption(
        "The recruiter replied — tell AIROS **what** the response was, **how** it arrived, "
        "and (for an interview request) the date, time and manner."
    )

    resp_type = st.radio(
        "What was the response?",
        options=[RESPONSE_REFUSED, RESPONSE_INTERVIEW, RESPONSE_ADDITIONAL_INFO],
        format_func=lambda k: RESPONSE_TYPES.get(k, k),
        key=f"resp_type_{selected_app_id}",
        horizontal=True,
    )

    with st.form(f"recruiter_response_form_{selected_app_id}"):
        rch, rdt = st.columns(2)
        channel = rch.selectbox(
            "Communication channel",
            options=RESPONSE_CHANNELS,
            key=f"resp_channel_{selected_app_id}",
        )
        resp_date = rdt.date_input(
            "Response date",
            value=datetime.now().date(),
            key=f"resp_date_{selected_app_id}",
        )
        resp_note = st.text_area(
            "Summary / notes (what did they say?)",
            height=80,
            key=f"resp_note_{selected_app_id}",
        )

        # Enhancement #2 — an interview request immediately asks for date/time/manner.
        if resp_type == RESPONSE_INTERVIEW:
            st.markdown("**🗓️ Interview scheduling (requested by the recruiter)**")
            iv1, iv2, iv3 = st.columns(3)
            iv_date = iv1.date_input(
                "Proposed interview date",
                value=datetime.now().date(),
                key=f"iv_date_{selected_app_id}",
            )
            iv_time = iv2.time_input(
                "Proposed interview time",
                value=datetime.now().time().replace(minute=0, second=0, microsecond=0),
                key=f"iv_time_{selected_app_id}",
            )
            iv_mode = iv3.selectbox(
                "Manner of the interview",
                options=INTERVIEW_MODES,
                key=f"iv_mode_{selected_app_id}",
            )

        resp_submitted = st.form_submit_button("💾 Record Recruiter Response", type="primary")

    if resp_submitted:
        try:
            updated = record_employer_response(
                selected_app_id,
                response_type=resp_type,
                channel=channel,
                responded_at=resp_date,
                note=resp_note,
            )
        except ValueError as e:
            st.error(str(e))
            updated = None
        if updated:
            st.success(f"✅ Response recorded → **{STATUS_LABELS.get(updated['status'], updated['status'])}**")
            if resp_type == RESPONSE_INTERVIEW:
                pending = get_pending_interview(updated)
                if pending:
                    combined = datetime.combine(iv_date, iv_time)
                    try:
                        schedule_interview(
                            selected_app_id,
                            pending["round"],
                            combined,
                            mode=iv_mode,
                            notes="Scheduled from the recruiter's interview request.",
                        )
                        st.success(f"🗓️ Interview scheduled: **{iv_date} {iv_time.strftime('%H:%M')}** — {iv_mode}")
                    except ValueError as e:
                        st.error(str(e))
            st.rerun()

    # ── Recruiter response history ──
    responses = app.get("recruiter_responses", [])
    if responses:
        st.markdown("#### 📋 Response history")
        for r in responses:
            st.markdown(
                f"- **{r.get('responded_on', '')}** · {r.get('type_label', r.get('type'))} "
                f"· via {r.get('channel', '—')}" + (f" — {r.get('note', '')}" if r.get("note") else "")
            )

    st.markdown("---")

# ──────────────────────────────────────────────
# STAGE 3 — FOLLOW-UP (an ACTION, not a lifecycle status)
# ──────────────────────────────────────────────
if current_status == WAITING:
    st.markdown("---")
    st.subheader("📤 Follow-Up")

    fu = follow_up_context(app)
    if fu["checkpoint"]:
        if fu["overdue"]:
            st.warning(f"⚠️ Follow-up checkpoint was **{fu['checkpoint']}** — {abs(fu['days_left'])} day(s) overdue. Consider a follow-up.")
        else:
            st.info(f"Follow-up checkpoint: **{fu['checkpoint']}** — {fu['days_left']} day(s) remaining.")

    st.markdown(
        "Follow-up is **an action, not a status**. Your status stays **WAITING** while you choose one of the following:"
    )

    fu_col1, fu_col2 = st.columns(2)

    with fu_col1:
        # A. Draft follow-up
        st.markdown("#### A. 📝 Draft follow-up")
        if st.button("Prepare follow-up draft", key="draft_fu_btn"):
            draft = draft_follow_up(app)
            st.info("Draft ready — send it externally, then confirm with **B. Mark as Contacted**.")
            st.code(draft["message"], language="text")

        # B. Mark as contacted
        st.markdown("#### B. ✅ Mark as Contacted")
        with st.form("form_mark_contacted"):
            contact_date = st.date_input("Contacted on", value=datetime.now().date())
            contact_channel = st.selectbox(
                "Channel",
                options=["Email", "LinkedIn message", "Phone call", "Recruiter message", "Other"],
            )
            contact_note = st.text_area("Note (what was sent / response so far)", height=80)
            marked = st.form_submit_button("Mark as Contacted", type="primary")
        if marked:
            mark_contacted(
                selected_app_id,
                contacted_at=contact_date,
                channel=contact_channel,
                note=contact_note,
            )
            st.success("📤 Contacted recorded — you remain in **WAITING**.")
            st.rerun()

    with fu_col2:
        # C. Remind me later
        st.markdown("#### C. ⏰ Remind Me Later")
        with st.form("form_remind_later"):
            later_date = st.date_input(
                "Remind me on",
                value=follow_up_checkpoint_date(app),
            )
            if st.form_submit_button("Remind Me Later"):
                remind_me_later(selected_app_id, later_date)
                st.success(f"⏰ Next check moved to **{later_date}**.")
                st.rerun()

        # Follow-up history
        st.markdown("#### 📋 Follow-up history")
        follow_ups = app.get("follow_ups", [])
        if follow_ups:
            for f in follow_ups:
                st.markdown(f"- **{f.get('sent_date', '')}** · {f.get('channel', f.get('method', ''))} — {f.get('note', '')}")
        else:
            st.caption("No follow-ups recorded yet.")

        st.markdown("#### 🔄 What's next")
        st.markdown("After any follow-up, keep monitoring while **WAITING** — or use **Update Status** below to record the employer's response.")

# ──────────────────────────────────────────────
# STAGE 4 — INTERVIEW SCHEDULING (Enhancement #2)
#     When a recruiter requests an interview, AIROS asks for the
#     date + time and the manner (online / Skype / G-Meet / Teams / ...).
# ──────────────────────────────────────────────
if current_status == INTERVIEW:
    pending_iv = get_pending_interview(app)
    st.markdown("## 🪑 Interview Scheduling")
    if pending_iv:
        st.info(
            f"Recruiter requested an interview (round {pending_iv['round']}). "
            "Confirm the **date + time** and the **manner** so AIROS can track it."
        )

    next_round_no = max([iv.get("round", 0) for iv in app.get("interviews", [])], default=0) + 1
    default_round = pending_iv["round"] if pending_iv else next_round_no

    with st.expander("🗓️ Schedule / confirm an interview round", expanded=bool(pending_iv)):
        with st.form(f"schedule_interview_form_{selected_app_id}"):
            s1, s2, s3 = st.columns(3)
            s_round = s1.number_input(
                "Round", min_value=1, value=int(default_round), step=1,
                key=f"iv_sched_round_{selected_app_id}",
            )
            s_date = s2.date_input(
                "Date", value=datetime.now().date(),
                key=f"iv_sched_date_{selected_app_id}",
            )
            s_time = s3.time_input(
                "Time",
                value=datetime.now().time().replace(minute=0, second=0, microsecond=0),
                key=f"iv_sched_time_{selected_app_id}",
            )
            s_mode = st.selectbox(
                "Manner of the interview",
                options=INTERVIEW_MODES,
                key=f"iv_sched_mode_{selected_app_id}",
            )
            s_note = st.text_area(
                "Notes (link, contact person, preparation…)",
                height=70,
                key=f"iv_sched_note_{selected_app_id}",
            )
            s_submit = st.form_submit_button("💾 Save Interview", type="primary")
        if s_submit:
            combined = datetime.combine(s_date, s_time)
            try:
                schedule_interview(
                    selected_app_id,
                    int(s_round),
                    combined,
                    mode=s_mode,
                    notes=s_note,
                )
                st.success(f"🗓️ Interview round {int(s_round)} saved: **{s_date} {s_time.strftime('%H:%M')}** — {s_mode}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    ivs = app.get("interviews", [])
    if ivs:
        st.markdown("#### Upcoming / recorded interview rounds")
        for iv in ivs:
            when = iv.get("scheduled_at") or "**pending** ⏳"
            mode = iv.get("mode") or iv.get("format") or "—"
            note = f" — {iv.get('notes', '')}" if iv.get("notes") else ""
            st.markdown(f"- **Round {iv.get('round')}** · {when} · {mode}{note}")
    st.markdown("---")

# ──────────────────────────────────────────────
# Primary action: View Application (timeline + details)
# ──────────────────────────────────────────────
with st.expander("👁️ View Application — full record & timeline", expanded=False):
    st.markdown("#### Application record")
    if app.get("job_url"):
        st.markdown(f"**Job URL:** [{app['job_url']}]({app['job_url']})")
    st.markdown(f"**Application ID:** `{app.get('application_id')}`")
    st.markdown(f"**Recruiter interactions:** {len(app.get('recruiter_interactions', []))}")
    st.markdown(f"**Interviews:** {len(app.get('interviews', []))}")

    st.markdown("#### Lifecycle timeline")
    for entry in app.get("timeline", []):
        st.markdown(
            f"- **{STATUS_LABELS.get(entry['status'], entry['status'])}** — "
            f"{entry['at']} — {entry.get('note', '')}"
        )

    st.markdown("#### Follow-ups sent")
    if app.get("follow_ups"):
        for f in app["follow_ups"]:
            st.markdown(
                f"- **{f.get('sent_date', '')}** · {f.get('method', '')} — {f.get('note', '')}"
            )
    else:
        st.caption("No follow-ups recorded yet.")

    st.markdown("#### Recruiter interactions")
    if app.get("recruiter_interactions"):
        for inter in app["recruiter_interactions"]:
            st.markdown(f"- {inter['at']} · **{inter['type']}** — {inter.get('note','')}")
    else:
        st.caption("No interactions logged yet.")

    st.markdown("#### Recruiter responses")
    if app.get("recruiter_responses"):
        for r in app["recruiter_responses"]:
            st.markdown(
                f"- {r.get('responded_on', '')} · **{r.get('type_label', r.get('type'))}** "
                f"· via {r.get('channel', '—')} — {r.get('note', '')}"
            )
    else:
        st.caption("No recruiter responses recorded yet.")

    st.markdown("#### Interview / assessment records")
    if app.get("interviews"):
        for iv in app["interviews"]:
            when = iv.get("scheduled_at") or "pending ⏳"
            mode = iv.get("mode") or iv.get("format") or "—"
            status_tag = " ⚠️ needs date/time" if iv.get("requested") and not iv.get("scheduled_at") else ""
            st.markdown(
                f"- Round {iv.get('round')} · {mode} · {when} — {iv.get('notes','')}{status_tag}"
            )
    else:
        st.caption("No interview rounds recorded yet.")
    if app.get("assessment"):
        st.markdown(f"- Assessment: {app['assessment']}")
    else:
        st.caption("No assessment recorded yet.")

    if app.get("notes"):
        st.markdown(f"**Notes:** {app['notes']}")

# ──────────────────────────────────────────────
# Secondary action: Update Status (manual transitions only)
# ──────────────────────────────────────────────
st.markdown("### ⚙️ Update Status")
allowed = get_valid_transitions(current_status)

if not allowed:
    st.info("This application is in a terminal state and cannot be advanced further.")
elif current_status == "OFFER":
    st.markdown("🎉 **Offer received.** Close the application to finalise it.")
    with st.form("close_app_form"):
        close_note = st.text_input("Closing note (optional)")
        if st.form_submit_button("🗂️ Close Application", type="primary"):
            from utils.tracker import close_application
            closed = close_application(selected_app_id, close_note)
            if closed:
                st.success(f"Application closed → {closed['application_id']}")
                st.rerun()
else:
    with st.container(border=True):
        st.caption(
            "💡 For a recruiter reply, use the **💬 Recruiter Response** section above — "
            "it records the outcome + channel and moves the status automatically."
        )
    with st.form("update_status_form"):
        st.markdown(f"**From:** {STATUS_LABELS.get(current_status, current_status)}")
        target = st.selectbox(
            "Move to (valid next status)",
            options=[STATUS_LABELS.get(s, s) for s in allowed],
        )
        note = st.text_area("Note for this change (optional)", height=80)
        if st.form_submit_button("Update Status", type="primary"):
            # Map the human label back to the enum value
            target_enum = next(
                (s for s in allowed if STATUS_LABELS.get(s) == target),
                target,
            )
            try:
                updated = update_status(selected_app_id, target_enum, note=note)
            except ValueError as e:
                st.error(str(e))
                updated = None
            if updated:
                st.success(f"Status updated → **{STATUS_LABELS.get(target_enum, target_enum)}**")
                st.rerun()