import os
import sys
import streamlit as st

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
)

from database.crud import add_job_offer, get_all_jobs
from database.db import init_db
from utils.nav import render_sidebar

st.set_page_config(page_title="AIROS - Job Offers", layout="wide")
init_db()
render_sidebar()


# Page Configuration
st.set_page_config(page_title="AIROS - Job Offers", layout="wide")
init_db()

st.title("💼 Job Offers Manager")
st.markdown(
    "Save and categorize target job postings to prepare for ATS matching."
)

st.divider()

# --- FORM TO ADD A NEW JOB OFFER ---
st.subheader("➕ Add New Job Listing")

with st.form("add_job_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        title = st.text_input(
            "Job Title *", placeholder="e.g. Senior ERP Project Manager"
        )
        company_name = st.text_input("Company Name *", placeholder="e.g. SAP")
        location = st.text_input(
            "Location", placeholder="e.g. Remote / Germany / France"
        )

    with col2:
        target_role_category = st.selectbox(
            "Role Category *",
            [
                "ERP Project Manager",
                "IT Program Manager",
                "Project Controller",
                "Business Analyst",
                "PMO Manager",
                "Other",
            ],
        )
        url = st.text_input(
            "Job URL (Optional)",
            placeholder="https://linkedin.com/jobs/view/...",
        )

    description = st.text_area(
        "Job Description *",
        height=250,
        placeholder="Paste full job description text here (requirements, responsibilities, skills)...",
    )

    submitted = st.form_submit_button("💾 Save Job Offer")

    if submitted:
        if not title.strip() or not company_name.strip() or not description.strip():
            st.error(
                "Please fill in all required fields (Title, Company, and Description)."
            )
        else:
            add_job_offer(
                title=title,
                company_name=company_name,
                target_role_category=target_role_category,
                location=location,
                url=url,
                description=description,
            )
            st.success(
                f"Job offer '{title}' at {company_name} saved successfully!"
            )
            st.rerun()

st.divider()

# --- DISPLAY EXISTING JOBS LIST ---
st.subheader("📋 Saved Job Listings")

saved_jobs = get_all_jobs()

if not saved_jobs:
    st.info("No job listings saved yet. Use the form above to add your first job posting.")
else:
    for job in saved_jobs:
        with st.expander(
            f"📍 **{job['title']}** — {job['company_name']} ({job['target_role_category'] or 'General'})"
        ):
            col_a, col_b = st.columns(2)
            with col_a:
                st.caption(f"**Location:** {job['location'] or 'N/A'}")
                st.caption(f"**Added On:** {job['created_at']}")
            with col_b:
                if job["url"]:
                    st.caption(f"**Link:** [Job Posting URL]({job['url']})")

            st.markdown("---")
            st.text_area(
                "Description",
                value=job["description"],
                height=150,
                disabled=True,
                key=f"desc_{job['id']}",
            )