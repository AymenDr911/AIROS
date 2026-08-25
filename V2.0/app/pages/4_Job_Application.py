# app/pages/4_Job_Application.py
import sys
from pathlib import Path
import json
from datetime import datetime

app_dir = Path(__file__).resolve().parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

import streamlit as st
from utils.job import get_all_jobs, get_job, add_contact_to_job
from utils.contact import get_contact
from utils.company import get_company
from utils.document_storage import save_document, get_documents_for_job
from utils.document_engine import generate_application_documents
from utils.validation import validate_generated_documents
from utils.tracker import create_application, get_active_applications

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

# Core job details: Company, Location, Source, Job URL
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"**Company**  \n{job.get('company_id', '—')}")
with c2:
    st.markdown(f"**Location**  \n{job.get('location', '—')} · {job.get('country', '—')}")
with c3:
    st.markdown(f"**Source**  \n{job.get('source', '—')}")
with c4:
    job_url = job.get("job_url", "")
    if job_url:
        st.markdown(f"**Job URL**  \n[{job_url}]({job_url})")
    else:
        st.markdown("**Job URL**  \n—")

# Component scores
st.markdown("#### Component Scores")
ats_components = job.get("ats_components", {})
if ats_components:
    comp_cols = st.columns(4)
    for i, (comp_key, comp_val) in enumerate(ats_components.items()):
        comp_cols[i % 4].metric(
            comp_key.replace("_", " ").title(),
            f"{comp_val}%"
        )
else:
    st.caption("No component scores available for this job.")

# Strengths & Gaps
col_s, col_g = st.columns(2)

with col_s:
    st.markdown("#### ✅ Strengths")
    strengths = job.get("strengths", [])
    if strengths:
        st.success(", ".join(strengths[:30]))
    else:
        st.info("No strong matches detected.")

with col_g:
    st.markdown("#### ❌ Gaps")
    gaps = job.get("gap_analysis", [])
    if gaps:
        st.warning(", ".join(gaps[:30]))
    else:
        st.info("No significant gaps detected.")

# Evidence levels
st.markdown("#### Evidence Levels")
evidence = job.get("evidence", [])
if evidence:
    # Group evidence by category
    from collections import defaultdict
    evidence_by_cat = defaultdict(list)
    for ev in evidence:
        evidence_by_cat[ev.get("category", "other")].append(ev)

    for cat, items in evidence_by_cat.items():
        with st.expander(f"{cat.replace('_', ' ').title()} ({len(items)})", expanded=False):
            for ev in items:
                stars = ev.get("stars", "☆☆☆☆☆")
                source = ev.get("source", "—")
                st.markdown(f"- **{ev.get('item', '—')}** — {stars} `{source}`")
else:
    st.caption("No evidence matrix available for this job.")

# ------------------------------------------------------------------
# Company Review
# ------------------------------------------------------------------
st.markdown("---")
st.subheader("🏢 Company Review")

company = get_company(job.get("company_id", ""))
if company:
    with st.container(border=True):
        cc1, cc2, cc3 = st.columns(3)
        cc1.markdown(f"**Name**  \n{company.get('name', '—')}")
        cc2.markdown(f"**Industry**  \n{company.get('industry', '—')}")
        cc3.markdown(f"**Division**  \n{company.get('division', '—')}")

        cc4, cc5, cc6 = st.columns(3)
        cc4.markdown(f"**City**  \n{company.get('city', '—')}")
        cc5.markdown(f"**Country**  \n{company.get('country', '—')}")
        cc6.markdown(f"**Address**  \n{company.get('address', '—')}")

        cc7, cc8, cc9 = st.columns(3)
        cc7.markdown(f"**Website**  \n{company.get('website', '—')}")
        cc8.markdown(f"**LinkedIn**  \n{company.get('linkedin_url', '—')}")
        cc9.markdown(f"**Phone**  \n{company.get('phone', '—')}")
else:
    st.caption("No company details available for this job.")

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
            'confidence': session_contact.get('confidence', 'Medium'),
            'source': session_contact.get('source', 'Manual'),
        }

# Display recruiter status
if reliable_contact:
    st.success(
        f"✅ Reliable recruiter found: **{reliable_contact.get('name') or 'Unknown'}** "
        f"({reliable_contact.get('position') or '—'}) – {reliable_contact.get('email')}"
    )
    # Show confidence + source details
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        st.markdown(f"**Confidence**  \n{reliable_contact.get('confidence', '—')}")
    with rc2:
        st.markdown(f"**Source**  \n{reliable_contact.get('source', '—')}")
    with rc3:
        st.markdown(f"**Contact Type**  \n{reliable_contact.get('contact_type', '—')}")
else:
    st.info("ℹ️ No reliable individual recruiter email identified.")
    if contact_ids:
        st.caption(f"({len(contact_ids)} contact(s) linked but none passed the reliability check)")
    else:
        st.caption("No contacts linked to this job yet. Add recruiter info in ATS Analyzer.")

    # Manual recruiter form (only shown when no reliable contact exists)
    with st.expander("➕ Add Recruiter / HR Contact Manually", expanded=False):
        with st.form("manual_recruiter_form"):
            m1, m2 = st.columns(2)
            with m1:
                man_name = st.text_input("Name", placeholder="Anna Müller", key="man_rec_name")
                man_position = st.text_input("Position", placeholder="Senior Talent Acquisition", key="man_rec_position")
                man_email = st.text_input("Email", placeholder="anna.mueller@company.com", key="man_rec_email")
            with m2:
                man_linkedin = st.text_input("LinkedIn URL", placeholder="https://linkedin.com/in/...", key="man_rec_linkedin")
                man_type = st.selectbox(
                    "Contact Type",
                    ["HR Recruiter", "Talent Acquisition", "Hiring Manager", "General"],
                    key="man_rec_type",
                )
                man_confidence = st.selectbox("Confidence", ["High", "Medium", "Low"], index=1, key="man_rec_confidence")

            man_submitted = st.form_submit_button("💾 Save Recruiter", type="primary")

            if man_submitted:
                if man_name.strip() or man_email.strip():
                    # Save to session state
                    if 'job_contacts' not in st.session_state:
                        st.session_state['job_contacts'] = {}
                    st.session_state['job_contacts'][selected_job_id] = {
                        'name': man_name.strip(),
                        'position': man_position.strip(),
                        'email': man_email.strip(),
                        'linkedin_url': man_linkedin.strip(),
                        'contact_type': man_type,
                        'confidence': man_confidence,
                        'source': 'Manual',
                    }
                    # Also create a contact record linked to the job
                    if man_name.strip():
                        add_contact_to_job(
                            job_id=selected_job_id,
                            name=man_name,
                            position=man_position,
                            email=man_email,
                            linkedin_url=man_linkedin,
                            contact_type=man_type,
                            confidence=man_confidence,
                            source="Manual",
                        )
                    st.success("✅ Recruiter saved successfully!")
                    st.rerun()
                else:
                    st.warning("Please provide at least a name or an email.")

# ------------------------------------------------------------------
# 2. Application Preparation Zone
# ------------------------------------------------------------------
st.markdown("---")
st.subheader("🚀 Prepare Application")

st.markdown(
    "Generate your complete application package: **Tailored CV + Cover Letter** "
    "(and Recruiter Email if a reliable contact exists)."
)

existing_docs = get_documents_for_job(selected_job_id)

# Show existing documents if any
if any(existing_docs.values()):
    with st.expander("Previously generated documents", expanded=False):
        for doc_type, label in [("cv", "📄 CV"), ("cover_letter", "📝 Cover Letter"), ("recruiter_email", "✉️ Recruiter Email")]:
            if existing_docs[doc_type]:
                st.markdown(f"**{label}** ({len(existing_docs[doc_type])} version(s))")
                for p in existing_docs[doc_type]:
                    st.code(p, language=None)

# Prepare Application button
if st.button("🚀 Prepare Application", type="primary", use_container_width=True, key="btn_prepare_app"):
    with st.spinner("Generating your application package with Gemini (Document Engine)..."):
        result = generate_application_documents(
            job_id=selected_job_id,
            generate_cv=True,
            generate_cover_letter=True,
            generate_recruiter_email=True,
        )

        if "error" in result:
            st.error(result["error"])
        else:
            # ---- Save CV ----
            cv_data = result.get("cv", {})
            cv_full_text = cv_data.get("full_text") or json.dumps(cv_data, indent=2)
            cv_path = save_document(selected_job_id, "cv", cv_full_text, extension="txt")
            save_document(selected_job_id, "cv_structured", cv_data, extension="json")

            # ---- Save Cover Letter ----
            cl_data = result.get("cover_letter", {})
            cl_full_text = cl_data.get("full_text") or json.dumps(cl_data, indent=2)
            cl_path = save_document(selected_job_id, "cover_letter", cl_full_text, extension="txt")
            save_document(selected_job_id, "cover_letter_structured", cl_data, extension="json")

            st.success("✅ Application package generated!")

            # ---- Display CV ----
            with st.expander("📄 Tailored CV", expanded=True):
                st.text(cv_full_text)

            # ---- Display Cover Letter ----
            with st.expander("📝 Cover Letter", expanded=True):
                st.text(cl_full_text)

            # ---- Recruiter Email (conditional) ----
            email_data = result.get("recruiter_email", {})
            email_path = ""
            if email_data.get("required"):
                email_path = save_document(selected_job_id, "recruiter_email", email_data, extension="json")
                st.success(f"✅ Recruiter Email generated and saved → `{email_path}`")
                with st.expander("✉️ Recruiter Email", expanded=True):
                    st.markdown(f"**To:** {email_data.get('to')}")
                    st.markdown(f"**Subject:** {email_data.get('subject')}")
                    st.text_area("Email body", value=email_data.get("body", ""), height=220, key="email_body_preview")
            else:
                st.info("ℹ️ No reliable individual recruiter email was identified. Recruiter email was not generated.")

            # Record when the package was generated + which versions were used (Stage 1)
            # time consumed = confirmation time - document generation time
            st.session_state[f"docs_generated_at_{selected_job_id}"] = datetime.now().isoformat(timespec="seconds")
            st.session_state[f"docs_cv_path_{selected_job_id}"] = cv_path
            st.session_state[f"docs_cl_path_{selected_job_id}"] = cl_path
            st.session_state[f"docs_email_path_{selected_job_id}"] = email_path if email_data.get("required") else ""

            # ---- Optimization Report ----
            opt_report = result.get("optimization_report", {})
            if opt_report:
                with st.expander("📊 Optimization Report", expanded=False):
                    st.markdown(f"**Target keywords used:** {', '.join(opt_report.get('target_keywords_used', [])) or '—'}")
                    st.markdown(f"**Strengths emphasized:** {', '.join(opt_report.get('strengths_emphasized', [])) or '—'}")
                    st.markdown(f"**Gaps not claimed:** {', '.join(opt_report.get('gaps_not_claimed', [])) or '—'}")
                    st.markdown(f"**Evidence based:** {'✅ Yes' if opt_report.get('evidence_based') else '❌ No'}")

            # ---- Post-Generation Validation (Step 11) ----
            validation = validate_generated_documents(result, job)
            st.session_state["last_validation"] = validation

            with st.expander("✅ Validation Report", expanded=True):
                # ATS comparison
                v1, v2, v3 = st.columns(3)
                v1.metric("Original ATS", f"{validation.get('original_ats', 0)}%")
                v2.metric("Tailored CV ATS", f"{validation.get('tailored_ats', 0)}%")
                v3.metric("Improvement", f"{validation.get('improvement', 0):+d} points")

                if validation.get("status") == "improved":
                    st.success(validation.get("message", ""))
                elif validation.get("status") == "regressed":
                    st.error(validation.get("message", ""))
                else:
                    st.info(validation.get("message", ""))

                # Evidence validation
                ev = validation.get("evidence_validation", {})
                if ev.get("unsupported_count", 0) > 0:
                    st.warning(f"⚠️ {ev.get('unsupported_count')} unsupported skill(s): {', '.join(ev.get('unsupported_skills', []))}")
                else:
                    st.success(f"✅ All {ev.get('checked', 0)} skills are evidence-supported.")

                # Fabrication check
                fab = validation.get("fabrication_check", {})
                if fab.get("fabrications_found", False):
                    st.error(f"🚨 Fabrication detected: {fab.get('fabrications', [])}")
                else:
                    st.success("✅ No fabrications detected.")

                if validation.get("needs_review", False):
                    st.error("⚠️ This document requires review/regeneration.")

            # ---- Application Package Preview (Step 12) ----
            st.markdown("---")
            st.subheader("📦 Application Package")

            with st.container(border=True):
                p1, p2, p3 = st.columns(3)
                p1.markdown(f"**Job**  \n{job.get('title', '—')}")
                p2.markdown(f"**Company**  \n{company.get('name', job.get('company_id', '—'))}")
                p3.markdown(f"**ATS Score**  \n{job.get('ats_score', 0)}%")

                st.markdown("---")
                st.markdown("**Generated Documents:**")
                st.markdown(f"- ✅ **Tailored CV** → `{cv_path}`")
                st.markdown(f"- ✅ **Cover Letter** → `{cl_path}`")
                if email_data.get("required"):
                    st.markdown(f"- ✅ **Recruiter Email** → `{email_path}`")
                else:
                    st.markdown("- ⚠️ **Recruiter Email** — Not applicable (no reliable individual recruiter email identified)")

                st.markdown("---")
                r1, r2 = st.columns(2)
                with r1:
                    if reliable_contact:
                        st.markdown(f"**Recruiter**  \n{reliable_contact.get('name', '—')} ({reliable_contact.get('email', '—')})")
                    else:
                        st.markdown("**Recruiter**  \n—")
                with r2:
                    st.markdown("**Application Status**  \n📝 Not yet submitted")
                    st.markdown("**Application Channel**  \n— (to be confirmed after external application)")

                st.caption("The documents are not yet considered submitted. Apply externally, then confirm below.")

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
            # Gather the document versions that were used (Stage 1: preserve exact CV/document versions)
            docs = {
                "cv_path": st.session_state.get(f"docs_cv_path_{selected_job_id}", ""),
                "cover_letter_path": st.session_state.get(f"docs_cl_path_{selected_job_id}", ""),
                "email_path": st.session_state.get(f"docs_email_path_{selected_job_id}", ""),
            }
            docs_generated_at = st.session_state.get(f"docs_generated_at_{selected_job_id}", "")

            # Create + persist the tracking record via the tracker (status = APPLIED)
            application = create_application(
                job=job,
                channel=channel,
                application_date=app_date,
                notes=notes,
                recruiter=reliable_contact,
                docs=docs,
                docs_generated_at=docs_generated_at,
            )
            app_id = application["application_id"]
            st.success(f"✅ Application recorded → **{app_id}** (status: **APPLIED**)")
            st.balloons()
            st.info("➡️ Track this application in the **Job Tracking** page (sidebar).")
        else:
            st.info("Application marked as Cancelled / Not sent. No Application record created.")