import sys
from pathlib import Path

# Fix Python path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st
from services.session_manager import initialize_session, logout
from components.footer import render_footer

# ──────────────────────────────────────────────
# Page Config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="AIROS V2",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

initialize_session()
# ──────────────────────────────────────────────
# 1. Authentication Gate
# ──────────────────────────────────────────────
if not st.session_state.get("logged_in", False):
    # Hide sidebar when not logged in
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important;}
            [data-testid="stSidebarNav"] {display: none !important;}
        </style>
    """, unsafe_allow_html=True)
    from auth import render_auth
    render_auth()
    st.stop()

# ──────────────────────────────────────────────
# 2. Profile Completeness Check  ← THIS WAS MISSING
# ──────────────────────────────────────────────
def is_profile_complete() -> bool:
    required = [
        "career_stage",
        "personal_identity",
        "education",
        "experience",
        "skills",
    ]
    for key in required:
        if key not in st.session_state or not st.session_state[key]:
            return False
    return True

# Force onboarding if profile is incomplete
if not is_profile_complete():
    st.switch_page("pages/onboarding.py")
    st.stop()

# ──────────────────────────────────────────────
# 3. User is logged in + Profile is complete
# → Show main navigation
# ──────────────────────────────────────────────
main_pages = [
    st.Page("pages/2_Dashboard.py", title="Dashboard", icon="🏠", default=True),
    st.Page("pages/profile.py", title="Profile", icon="👤"),
    st.Page("pages/3_ATS_Analyzer.py", title="ATS Analyzer", icon="📄"),
]

jobs = st.session_state.get("jobs", {})
if jobs:
    main_pages.append(
        st.Page("pages/4_Job_Application.py", title="Job Application", icon="📋")
    )

pages = {"Main": main_pages}
pg = st.navigation(pages)
pg.run()