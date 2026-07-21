import streamlit as st

def navigate_to(target_filename: str):
    """
    Dynamically resolves page paths across all execution environments
    (Local vs Streamlit Cloud root vs Subfolder execution).
    """
    # Strategy 1: Search Streamlit's internal page registry directly
    try:
        from streamlit.source_util import get_pages
        pages = get_pages("")
        clean_target = target_filename.replace(".py", "")
        
        for page_info in pages.values():
            script_path = page_info.get("script_path", "")
            page_name = page_info.get("page_name", "")
            
            if script_path.endswith(target_filename) or page_name == clean_target:
                st.switch_page(script_path)
                return
    except Exception:
        pass

    # Strategy 2: Fallback path candidates
    candidates = [
        f"app/pages/{target_filename}",
        f"pages/{target_filename}",
        f"app/{target_filename}",
        target_filename
    ]
    
    for candidate in candidates:
        try:
            st.switch_page(candidate)
            return
        except Exception:
            continue

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
        navigate_to("Home.py")

    if st.sidebar.button("💼 Jobs", key="nav_jobs", use_container_width=True):
        navigate_to("2_Jobs.py")

    if st.sidebar.button("🎯 ATS Analyzer", key="nav_ats", use_container_width=True):
        st.info("ATS Analyzer page coming in Sprint 2!")

    if st.sidebar.button("📄 CV Manager", key="nav_cv", use_container_width=True):
        navigate_to("1_CV_Manager.py")

    if st.sidebar.button("📋 Applications", key="nav_apps", use_container_width=True):
        st.info("Applications page coming soon!")

    if st.sidebar.button("📊 Analytics", key="nav_analytics", use_container_width=True):
        st.info("Analytics page coming soon!")