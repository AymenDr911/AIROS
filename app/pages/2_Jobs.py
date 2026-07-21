import sys
from pathlib import Path

# Add project root directory (.../AIROS) to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from database.crud import add_job_offer, get_all_jobs, delete_job
from utils.nav import render_sidebar

st.set_page_config(page_title="AIROS - Jobs", page_icon="💼", layout="wide")

render_sidebar()

st.title("💼 Job Offers Manager")
st.markdown("Save and organize target job postings before running ATS comparisons.")

st.subheader("➕ Add New Job Listing")

with st.form("add_job_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Job Title *", placeholder="e.g. Senior ERP Project Manager")
        company = st.text_input("Company Name *", placeholder="e.g. SAP / Odoo / Microsoft")
        location = st.text_input("Location", placeholder="e.g. Remote / France / Germany / Tunisia")
    with col2:
        role_category = st.selectbox("Role Category *", ["ERP Project Manager", "IT Program Manager", "Scrum Master / Agile Lead", "Solution Architect", "Other"])
        work_type = st.selectbox("Work Type", ["Full-time", "Contract / Freelance", "Part-time"])
        url = st.text_input("Job URL (Optional)", placeholder="https://linkedin.com/jobs/view/...")

    description = st.text_area("Job Description *", placeholder="Paste full job description text here...", height=200)
    questions = st.text_area("Specific Application Questions (Optional)", placeholder="Paste custom application questions...", height=80)

    submitted = st.form_submit_button("💾 Save Job Offer")

    if submitted:
        if not title or not company or not description:
            st.error("Please fill in all required fields (Job Title, Company Name, Job Description).")
        else:
            job_id = add_job_offer(
                title=title,
                company=company,
                role_category=role_category,
                location=location,
                work_type=work_type,
                url=url,
                description=description,
                questions=questions
            )
            st.success(f"✅ Job offer saved successfully with ID: {job_id}")
            st.rerun()

st.divider()
st.subheader("📋 Saved Job Listings")

jobs = get_all_jobs()

if not jobs:
    st.info("No job listings saved yet. Use the form above to add your first job posting.")
else:
    for job in jobs:
        with st.expander(f"💼 {job['title']} @ {job['company']} (ID: {job['id']})"):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Category:** {job['role_category'] or 'N/A'}")
            c2.write(f"**Location:** {job['location'] or 'N/A'}")
            c3.write(f"**Work Type:** {job['work_type'] or 'N/A'}")
            
            if job['url']:
                st.markdown(f"🔗 [View Job Announcement]({job['url']})")
            
            st.markdown("**Description:**")
            st.text_area("Description Text", value=job['description'], height=120, disabled=True, key=f"desc_{job['id']}")
            
            if st.button("🗑️ Delete Job", key=f"del_{job['id']}"):
                delete_job(job['id'])
                st.success("Job deleted successfully.")
                st.rerun()