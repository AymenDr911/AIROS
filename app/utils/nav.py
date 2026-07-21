import streamlit as st

def render_sidebar():
    """Renders a consistent, custom sidebar navigation across all pages."""
    st.markdown(
        """
        <style>
            [data-testid="stSidebarNav"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True
    )

    st.sidebar.title("AIROS")
    st.sidebar.caption("Recruitment Operating System")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Menu")

    if st.sidebar.button("🏠 Dashboard", key="nav_dash", use_container_width=True):
        st.switch_page("Home.py")

    if st.sidebar.button("💼 Jobs", key="nav_jobs", use_container_width=True):
        st.switch_page("pages/2_Jobs.py")

    if st.sidebar.button("🎯 ATS Analyzer", key="nav_ats", use_container_width=True):
        st.info("ATS Analyzer page coming in Sprint 2!")

    if st.sidebar.button("📄 CV Manager", key="nav_cv", use_container_width=True):
        st.switch_page("pages/1_CV_Manager.py")

    if st.sidebar.button("📋 Applications", key="nav_apps", use_container_width=True):
        st.info("Applications page coming soon!")

    if st.sidebar.button("📊 Analytics", key="nav_analytics", use_container_width=True):
        st.info("Analytics page coming soon!")