# app/pages/4_Job_Application.py
import sys
from pathlib import Path
import json
from datetime import datetime

app_dir = Path(__file__).resolve().parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

import streamlit as st
from utils.job import get_all_jobs, get_job
from utils.contact import get_contact
from utils.document_storage import save_document, get_documents_for_job
from utils.document_engine import generate_application_documents

st.set_page_config(page_title="Job Application", page_icon="📋", layout="wide")
st.title("📋 Job Application")
st.caption("Generate application documents and confirm when you have applied externally.")

# ------------------------------------------------------------------
# 1. Select a saved Job
# ------------------------------------------------------------------
jobs = get_all_jobs()

if not jobs:
    st.warning("No saved jobs found. Please analyse and save a job in the **ATS Analyzer** first.")
    st.stop()

job_options = {
    f"{j['job_id']} – {j.get('title', 'Untitled')}": j["job_id"]
    for j in jobs
}

selected_label = st.selectbox(
    "Select a saved Job",
    options=list(job_options.keys()),
    key="job_app_selected_job"
)
selected_job_id = job_options[selected_label]
job = get_job(selected_job_id)

if not job:
    st.error("Selected job not found.")
    st.stop()

# ------------------------------------------------------------------
# Job summary
# ------------------------------------------------------------------
st.markdown("---")
st.subheader("Job Summary")

col1, col2, col3 = st.columns(3)
col1.metric("Job Title", job.get("title", "—"))
col2.metric("ATS Score", f"{job.get('ats_score', 0)}%")
col3.metric("Recommendation", job.get("recommendation", "—"))

c1, c2 = st.columns(2)
with c1:
    st.markdown(f"**Company ID**  \n{job.get('company_id', '—')}")
with c2:
    st.markdown(f"**Location**  \n{job.get('location', '—')} · {job.get('country', '—')}")

# ------------------------------------------------------------------
# Recruiter Status - FIXED SECTION
# ------------------------------------------------------------------
st.markdown("#### Recruiter Status")

reliable_contact = None
generic_prefixes = ("info@", "contact@", "careers@", "jobs@", "hr@", "hello@", "recruitment@", "noreply@")

# Method 1: Try to get contact from database via contact_ids
contact_ids = job.get("contact_ids", [])
if contact_ids:
    for cid in contact_ids:
        contact = get_contact(cid)
        if not contact:
            continue
        email = (contact.get("email") or "").strip().lower()
        if not email:
            continue
        # Accept if it does not look like a generic mailbox
        if not any(email.startswith(p) for p in generic_prefixes):
            reliable_contact = contact
            break

# Method 2: Fallback to session state (from ATS Analyzer form)
if not reliable_contact and 'job_contacts' in st.session_state:
    session_contact = st.session_state['job_contacts'].get(selected_job_id, {})
    email = session_contact.get('email', '').strip().lower()
    
    if email and not any(email.startswith(p) for p in generic_prefixes):
        reliable_contact = {
            'name': session_contact.get('name', 'Unknown'),
            'position': session_contact.get('position', '—'),
            'email': email,
            'linkedin_url': session_contact.get('linkedin_url', ''),
            'contact_type': session_contact.get('contact_type', 'HR Recruiter'),
        }

# Display recruiter status
if reliable_contact:
    st.success(
        f"✅ Reliable recruiter found: **{reliable_contact.get('name') or 'Unknown'}** "
        f"({reliable_contact.get('position') or '—'}) – {reliable_contact.get('email')}"
    )
else:
    st.info("ℹ️ No reliable individual recruiter email identified.")
    if contact_ids:
        st.caption(f"({len(contact_ids)} contact(s) linked but none passed the reliability check)")
    else:
        st.caption("No contacts linked to this job yet. Add recruiter info in ATS Analyzer.")

# ------------------------------------------------------------------
# 2. Document Generation Zone
# ------------------------------------------------------------------
st.markdown("---")
st.subheader("Document Generation")

existing_docs = get_documents_for_job(selected_job_id)

tab_cv, tab_cl, tab_email = st.tabs([
    "📄 Generate Tailored CV",
    "📝 Generate Cover Letter",
    "✉️ Generate Recruiter Email"
])

# ---------- CV Tab ----------
with tab_cv:
    st.markdown("Generate a CV optimised for this specific job.")
    if existing_docs["cv"]:
        st.caption(f"Previously generated: {len(existing_docs['cv'])} version(s)")
        for p in existing_docs["cv"]:
            st.code(p, language=None)

    if st.button("Generate Tailored CV", type="primary", key="btn_cv"):
        with st.spinner("Generating tailored CV with Gemini (Document Engine)..."):
            result = generate_application_documents(
                job_id=selected_job_id,
                generate_cv=True,
                generate_cover_letter=False,
                generate_recruiter_email=False,
            )

            if "error" in result:
                st.error(result["error"])
            else:
                cv_data = result.get("cv", {})
                full_text = cv_data.get("full_text") or json.dumps(cv_data, indent=2)
                path = save_document(selected_job_id, "cv", full_text, extension="txt")
                save_document(selected_job_id, "cv_structured", cv_data, extension="json")
                st.success(f"✅ Tailored CV generated and saved → `{path}`")
                with st.expander("Preview CV"):
                    st.text(full_text)

# ---------- Cover Letter Tab ----------
with tab_cl:
    st.markdown("Generate a personalised cover letter for this company and role.")
    if existing_docs["cover_letter"]:
        st.caption(f"Previously generated: {len(existing_docs['cover_letter'])} version(s)")
        for p in existing_docs["cover_letter"]:
            st.code(p, language=None)

    if st.button("Generate Cover Letter", type="primary", key="btn_cl"):
        with st.spinner("Generating cover letter with Gemini (Document Engine)..."):
            result = generate_application_documents(
                job_id=selected_job_id,
                generate_cv=False,
                generate_cover_letter=True,
                generate_recruiter_email=False,
            )

            if "error" in result:
                st.error(result["error"])
            else:
                cl_data = result.get("cover_letter", {})
                full_text = cl_data.get("full_text") or json.dumps(cl_data, indent=2)
                path = save_document(selected_job_id, "cover_letter", full_text, extension="txt")
                save_document(selected_job_id, "cover_letter_structured", cl_data, extension="json")
                st.success(f"✅ Cover Letter generated and saved → `{path}`")
                with st.expander("Preview Cover Letter"):
                    st.text(full_text)

# ---------- Recruiter Email Tab ----------
with tab_email:
    if not reliable_contact:
        st.warning("⚠️ No verified recruiter contact available. This option is disabled.")
        st.caption("A reliable individual email (High/Medium confidence, non-generic) is required.")
        st.info("💡 Tip: Add recruiter details when saving the job in **ATS Analyzer**.")
    else:
        st.markdown(
            f"Generate a formal email to **{reliable_contact.get('name')}** "
            f"({reliable_contact.get('email')})."
        )
        if existing_docs["recruiter_email"]:
            st.caption(f"Previously generated: {len(existing_docs['recruiter_email'])} version(s)")
            for p in existing_docs["recruiter_email"]:
                st.code(p, language=None)

        if st.button("Generate Recruiter Email", type="primary", key="btn_email"):
            with st.spinner("Generating recruiter email with Gemini (Document Engine)..."):
                result = generate_application_documents(
                    job_id=selected_job_id,
                    generate_cv=False,
                    generate_cover_letter=False,
                    generate_recruiter_email=True,
                )

                if "error" in result:
                    st.error(result["error"])
                else:
                    email_data = result.get("recruiter_email", {})
                    if not email_data.get("required"):
                        st.warning(email_data.get("message", "Recruiter email not generated."))
                    else:
                        path = save_document(selected_job_id, "recruiter_email", email_data, extension="json")
                        st.success(f"✅ Recruiter Email generated and saved → `{path}`")
                        st.markdown(f"**To:** {email_data.get('to')}")
                        st.markdown(f"**Subject:** {email_data.get('subject')}")
                        st.text_area("Email body", value=email_data.get("body", ""), height=220, key="email_body_preview")

# ------------------------------------------------------------------
# 3. Confirm Application
# ------------------------------------------------------------------
st.markdown("---")
st.subheader("✅ Confirm Application")

st.markdown(
    "After you have applied **externally** (LinkedIn, company site, email…), "
    "come back here and confirm the outcome."
)

with st.form("confirm_application_form"):
    st.markdown(f"**Job:** {job.get('title')}  \n**Company ID:** {job.get('company_id')}")

    status = st.radio(
        "Application Status",
        options=["Sent successfully", "Cancelled / Not sent"],
        horizontal=True
    )

    channel = None
    app_date = None
    notes = ""

    if status == "Sent successfully":
        channel = st.selectbox(
            "Application Channel",
            options=[
                "Job Platform (LinkedIn)",
                "Job Platform (StepStone)",
                "Job Platform (Indeed)",
                "Job Platform (Other)",
                "Company Career Site",
                "Direct Email to Recruiter",
            ]
        )
        app_date = st.date_input("Application Date", value=datetime.now().date())
        notes = st.text_area("Notes (optional)", height=80)

    submitted = st.form_submit_button("Confirm", type="primary")

    if submitted:
        if status == "Sent successfully":
            if "applications" not in st.session_state:
                st.session_state.applications = {}

            app_id = f"APP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            application = {
                "application_id": app_id,
                "job_id": selected_job_id,
                "candidate_id": st.session_state.get("candidate_id", "CAND-UNKNOWN"),
                "company_id": job.get("company_id"),
                "status": "APPLIED",
                "application_date": str(app_date),
                "channel": channel,
                "notes": notes,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            st.session_state.applications[app_id] = application
            st.success(f"✅ Application recorded → **{app_id}**")
            st.balloons()
        else:
            st.info("Application marked as Cancelled / Not sent. No Application record created.")