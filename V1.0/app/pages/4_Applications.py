import sys
from pathlib import Path

# Add project root directory (.../AIROS) to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))



import streamlit as st
from database.crud import get_all_jobs, get_all_applications, add_application, update_application_status, get_custom_cvs_for_job
from utils.nav import render_sidebar

st.set_page_config(page_title="AIROS - Applications", page_icon="📋", layout="wide")

render_sidebar()

st.title("📋 Application Tracker")
st.markdown("Track submitted job applications and update interview status in real-time.")

st.subheader("➕ Log New Application")

jobs = get_all_jobs()

if not jobs:
    st.warning("No jobs found. Please add a job posting in the Jobs page first.")
else:
    job_map = {f"{j['title']} @ {j['company']} (ID: {j['id']})": j for j in jobs}
    selected_job_label = st.selectbox("Select Target Job:", list(job_map.keys()))
    selected_job = job_map[selected_job_label]

    custom_cvs = get_custom_cvs_for_job(selected_job['id'])

    if not custom_cvs:
        st.warning(f"No custom CV generated for Job ID {selected_job['id']} yet. Generate one in ATS Analyzer first.")
    else:
        cv_map = {f"Custom CV #{c['id']} (ATS Score: {c['ats_score']}%)": c for c in custom_cvs}
        selected_cv_label = st.selectbox("Select Custom CV Version Used:", list(cv_map.keys()))
        selected_cv = cv_map[selected_cv_label]

        with st.form("log_app_form"):
            method = st.selectbox("Application Method", ["Direct Email", "Company Portal / Recruiter Site", "LinkedIn", "StepStone", "Indeed", "Other"])
            status = st.selectbox("Initial Status", ["Applied", "Screening", "Interview Scheduled", "Offer Received", "Rejected", "Withdrawn"])
            notes = st.text_area("Notes", placeholder="e.g. Sent application directly to hiring manager...")

            submitted = st.form_submit_button("📌 Save Application Record")
            if submitted:
                app_id = add_application(
                    job_id=selected_job['id'],
                    cv_id=selected_cv['id'],
                    method=method,
                    status=status,
                    notes=notes
                )
                st.success(f"✅ Application logged successfully (ID: {app_id})!")
                st.rerun()

st.divider()
st.subheader("📊 Application History")

apps = get_all_applications()

if not apps:
    st.info("No applications logged yet.")
else:
    for app in apps:
        with st.expander(f"📌 {app['job_title']} @ {app['company']} | Current Status: {app['status']}"):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Applied Date:** {app['applied_at']}")
            c2.write(f"**Method:** {app['method']}")
            c3.write(f"**ATS Match Score:** {app['ats_score']}%")

            status_list = ["Applied", "Screening", "Interview Scheduled", "Offer Received", "Rejected", "Withdrawn"]
            current_idx = status_list.index(app['status']) if app['status'] in status_list else 0
            
            new_status = st.selectbox("Update Status:", status_list, index=current_idx, key=f"status_{app['application_id']}")

            if st.button("Update Status", key=f"btn_{app['application_id']}"):
                update_application_status(app['application_id'], new_status)
                st.success("Status updated!")
                st.rerun()