import streamlit as st


def render_sidebar():
    with st.sidebar:
        st.markdown("## 🚀 **AIROS**")
        st.caption("Recruitment Operating System")
        st.divider()

        # Always visible pages
        st.page_link("Home.py", label="Dashboard", icon="🏠")
        st.page_link("pages/1_Login.py", label="Login", icon="🔑")
        st.page_link("pages/2_Dashboard.py", label="Dashboard", icon="📊")
        st.page_link("pages/3_ATS_Analyzer.py", label="ATS Analyzer", icon="🎯")

        # Conditional: only show when at least one Job has been saved
        jobs = st.session_state.get("jobs", {})
        if jobs:
            st.page_link(
                "pages/4_Job_Application.py",
                label="Job Application",
                icon="📋"
            )

        st.page_link("pages/profile.py", label="Profile", icon="👤")
        st.page_link("pages/onboarding.py", label="Onboarding", icon="🚀")