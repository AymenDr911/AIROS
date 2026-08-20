import streamlit as st
from services.profile_service import save_user_profile

def show_experience():
    st.title("Professional Experience")
    st.markdown("Add your professional experience. You can add multiple entries.")
    st.markdown("---")
    st.caption("Step 4 of 9 — Experience")
    st.progress(40)

    # -------------------------------------------------
    # Initialize
    # -------------------------------------------------
    if "experience_list" not in st.session_state:
        st.session_state.experience_list = []

    # -------------------------------------------------
    # Pre-fill only once from AI extraction
    # -------------------------------------------------
    if (
        st.session_state.get("profile_method") == "ai"
        and st.session_state.get("cv_extracted")
        and not st.session_state.get("_experience_prefilled")
    ):
        cv_data = st.session_state.cv_extracted
        ai_experiences = (
            cv_data.get("professional_experience")
            or cv_data.get("experience")
            or cv_data.get("experiences")
            or []
        )

        if ai_experiences and isinstance(ai_experiences, list):
            for exp in ai_experiences:
                if not isinstance(exp, dict):
                    continue

                description = exp.get("description", "") or ""
                achievements = exp.get("achievements", [])
                if achievements and isinstance(achievements, list):
                    bullets = "\n".join(f"• {a}" for a in achievements if a)
                    description = f"{description}\n{bullets}".strip()

                st.session_state.experience_list.append({
                    "company": exp.get("company", ""),
                    "title": exp.get("role") or exp.get("title", ""),
                    "location": exp.get("location", ""),
                    "employment_type": exp.get("employment_type", "Full-time"),
                    "start_date": exp.get("start_date", ""),
                    "end_date": exp.get("end_date", ""),
                    "currently_working": exp.get("currently_working", False),
                    "description": description
                })

            st.info(f"{len(ai_experiences)} experience entries pre-filled from your CV.")

        st.session_state._experience_prefilled = True

    # -------------------------------------------------
    # Show already added experiences
    # -------------------------------------------------
    if st.session_state.experience_list:
        st.subheader("Your Experience")
        for i, exp in enumerate(st.session_state.experience_list):
            period = exp.get("start_date", "")
            if exp.get("currently_working"):
                period += " → Present"
            elif exp.get("end_date"):
                period += f" → {exp['end_date']}"

            with st.expander(f"{exp.get('title', '')} — {exp.get('company', '')}", expanded=False):
                st.write(f"**Period:** {period}")
                st.write(f"**Type:** {exp.get('employment_type', '-')}")
                if exp.get("location"):
                    st.write(f"**Location:** {exp['location']}")
                if exp.get("description"):
                    st.write(exp["description"])

                if st.button("Remove", key=f"remove_exp_{i}"):
                    st.session_state.experience_list.pop(i)
                    st.rerun()

    # -------------------------------------------------
    # Add new experience
    # -------------------------------------------------
    st.markdown("### Add Experience")
    col1, col2 = st.columns(2)

    with col1:
        company = st.text_input("Company / Organization *", placeholder="e.g. Google, Self-employed")
        title = st.text_input("Job Title *", placeholder="e.g. Software Engineer, Product Manager")
        location = st.text_input("Location", placeholder="e.g. Remote, Paris, France")

    with col2:
        employment_type = st.selectbox(
            "Employment Type",
            ["Full-time", "Part-time", "Contract", "Internship", "Freelance", "Volunteer", "Other"]
        )
        start_date = st.text_input("Start Date *", placeholder="2021-03 or March 2021")
        currently_working = st.checkbox("I currently work here")
        end_date = ""
        if not currently_working:
            end_date = st.text_input("End Date", placeholder="2023-08 or August 2023")

    description = st.text_area(
        "Description / Achievements",
        placeholder="Key responsibilities, impact, technologies used...",
        height=120
    )

    if st.button("➕ Add this Experience", use_container_width=True):
        if not company or not title or not start_date:
            st.error("Company, Job Title and Start Date are required.")
        else:
            st.session_state.experience_list.append({
                "company": company.strip(),
                "title": title.strip(),
                "location": location.strip() if location else "",
                "employment_type": employment_type,
                "start_date": start_date.strip(),
                "end_date": end_date.strip() if end_date else None,
                "currently_working": currently_working,
                "description": description.strip() if description else ""
            })
            st.success("Experience added!")
            st.rerun()

    # -------------------------------------------------
    # Navigation
    # -------------------------------------------------
    st.markdown("---")
    col_btn1, col_btn2 = st.columns([1, 2])

    with col_btn1:
        if st.button("← Back"):
            st.session_state.onboarding_step = "education"
            st.rerun()

    with col_btn2:
        if st.button("Save & Continue →", type="primary", use_container_width=True):
            st.session_state.experience = st.session_state.experience_list
            save_user_profile()
            st.session_state.onboarding_step = "skills"
            st.success("Experience saved!")
            st.rerun()