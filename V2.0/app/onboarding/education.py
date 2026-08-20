import streamlit as st

def render_education():
    st.title("Education")
    st.markdown("Add your education background. You can add multiple entries.")
    st.markdown("---")
    st.caption("Step 3 of 9 — Education")
    st.progress(30)

    # -------------------------------------------------
    # Initialize
    # -------------------------------------------------
    if "education_list" not in st.session_state:
        st.session_state.education_list = []

    # -------------------------------------------------
    # Pre-fill from AI only once
    # -------------------------------------------------
    if (
        st.session_state.get("profile_method") == "ai"
        and st.session_state.get("cv_extracted")
        and st.session_state.cv_extracted.get("education")
        and not st.session_state.get("education_prefilled", False)
    ):
        ai_education = st.session_state.cv_extracted["education"]
        for edu in ai_education:
            st.session_state.education_list.append({
                "degree": edu.get("degree", ""),
                "institution": edu.get("institution", ""),
                "field_of_study": edu.get("field", ""),
                "status": "Completed",
                "start_year": edu.get("start_year", ""),
                "end_year": edu.get("end_year", ""),
                "location": edu.get("location", ""),
                "description": edu.get("description", "")
            })
        st.session_state.education_prefilled = True
        # Optional: keep a soft message (remove the next line if you want zero messages)
        # st.info(f"{len(ai_education)} education entries pre-filled from your CV.")

    # -------------------------------------------------
    # Show already added education
    # -------------------------------------------------
    if st.session_state.education_list:
        st.subheader("Your Education")
        for i, edu in enumerate(st.session_state.education_list):
            with st.expander(f"{edu['degree']} — {edu['institution']}", expanded=False):
                st.write(f"**Field:** {edu.get('field_of_study', '-')}")
                st.write(f"**Status:** {edu.get('status', '-')}")
                st.write(f"**Period:** {edu.get('start_year', '')} → {edu.get('end_year', '')}")
                if edu.get("location"):
                    st.write(f"**Location:** {edu.get('location')}")
                if st.button("Remove", key=f"remove_edu_{i}"):
                    st.session_state.education_list.pop(i)
                    st.rerun()

    # -------------------------------------------------
    # Add new education
    # -------------------------------------------------
    st.markdown("### Add Education")
    col1, col2 = st.columns(2)
    with col1:
        degree = st.text_input("Degree / Diploma *", placeholder="e.g. Master's Degree, Bachelor, PhD...")
        institution = st.text_input("Institution *", placeholder="e.g. University of Tunis")
        field = st.text_input("Field of Study", placeholder="e.g. Information Systems")
    with col2:
        status = st.selectbox("Status *", ["Completed", "In Progress", "Expected"])
        start_year = st.text_input("Start Year", placeholder="2019")
        end_year = st.text_input("End Year (or Expected)", placeholder="2023")

    if st.button("➕ Add this Education", use_container_width=True):
        if not degree or not institution:
            st.error("Degree and Institution are required.")
        else:
            st.session_state.education_list.append({
                "degree": degree.strip(),
                "institution": institution.strip(),
                "field_of_study": field.strip(),
                "status": status,
                "start_year": start_year.strip(),
                "end_year": end_year.strip()
            })
            st.success("Education added!")
            st.rerun()

    st.markdown("---")
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        if st.button("← Back"):
            st.session_state.onboarding_step = "personal_identity"
            st.rerun()
    with col_btn2:
        if st.button("Save & Continue →", type="primary", use_container_width=True):
            st.session_state.education = st.session_state.education_list
            st.session_state.onboarding_step = "experience"
            st.rerun()