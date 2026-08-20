import sys
from pathlib import Path
import os
from datetime import datetime

# Force the app/ folder into the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from services.session_manager import initialize_session, logout, require_auth
from components.footer import render_footer

# ──────────────────────────────────────────────
# Page Config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="AIROS – Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ──────────────────────────────────────────────
# Sidebar Control
# ──────────────────────────────────────────────
st.markdown("""
    <style>
        /* Hide unwanted pages */
        div[data-testid="stSidebarNav"] ul li:first-child {
            display: none !important;
        }
        div[data-testid="stSidebarNav"] ul li:has(a[href*="main"]),
        div[data-testid="stSidebarNav"] ul li:has(a[href*="Login"]),
        div[data-testid="stSidebarNav"] ul li:has(a[href*="login"]),
        div[data-testid="stSidebarNav"] ul li:has(a[href*="onboarding"]) {
            display: none !important;
        }
    </style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Auth + Profile Guard
# ──────────────────────────────────────────────
initialize_session()
require_auth()

def is_profile_complete() -> bool:
    required = ["career_stage", "personal_identity", "education"]
    for key in required:
        if key not in st.session_state or not st.session_state[key]:
            return False
    return True

if not is_profile_complete():
    st.warning("Your profile is incomplete. Please finish the onboarding process.")
    st.info("Click **onboarding** in the sidebar if it is visible, or log out and start again.")
    st.stop()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def get_user_name() -> str:
    identity = st.session_state.get("personal_identity", {})
    if isinstance(identity, dict):
        first = identity.get("first_name", "")
        last = identity.get("last_name", "")
        full = f"{first} {last}".strip()
        if full:
            return full
        if identity.get("full_name"):
            return identity["full_name"]
    return st.session_state.get("user", "Professional")

def get_career_stage() -> str:
    return st.session_state.get("career_stage", "Not set")

def get_target_info() -> str:
    """Return the most relevant job title from the profile."""
    experience = st.session_state.get("experience", [])
    if isinstance(experience, list) and experience:
        # Take the first (most recent) experience title
        first_exp = experience[0]
        if isinstance(first_exp, dict) and first_exp.get("title"):
            return first_exp["title"]

    # Fallback to cv_extracted
    cv = st.session_state.get("cv_extracted", {})
    if isinstance(cv, dict):
        exp_list = cv.get("experience") or cv.get("experiences") or []
        if exp_list and isinstance(exp_list[0], dict):
            return exp_list[0].get("title", "Professional")

    return "Professional Profile"

def calculate_profile_completion() -> int:
    score = 0
    if st.session_state.get("career_stage"): score += 15
    if st.session_state.get("personal_identity"): score += 20
    if st.session_state.get("education"): score += 20
    if st.session_state.get("experience"): score += 20
    if st.session_state.get("skills"): score += 15
    if st.session_state.get("languages"): score += 5
    if st.session_state.get("certifications"): score += 5
    return min(score, 100)

# Data
cv_versions = st.session_state.get("cv_versions", [])
ats_history = st.session_state.get("ats_history", [])
applications = st.session_state.get("applications", [])
completion = calculate_profile_completion()

# ──────────────────────────────────────────────
# 1. HEADER + Top Right User Bar
# ──────────────────────────────────────────────
col_header, col_user = st.columns([5, 2])

with col_header:
    st.title("AIROS Platform — Executive Command Center")
    st.markdown(f"### Welcome back, **{get_user_name()}**")
    st.markdown(f"**{get_career_stage()}**")
    st.caption(get_target_info())

with col_user:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="text-align: right; padding-top: 10px;">
            <span style="font-size: 1.05rem;">👤 <b>{get_user_name()}</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )
    if st.button("🚪 Logout", key="top_logout", use_container_width=True):
        logout()
        st.experimental_rerun()

st.markdown("---")

# ──────────────────────────────────────────────
# 2. CAREER OVERVIEW (4 KPI Cards)
# ──────────────────────────────────────────────
st.subheader("Career Overview")

k1, k2, k3, k4 = st.columns(4)

with k1:
    with st.container():
        # Count original CV + tailored versions
        original_count = 1 if (
            st.session_state.get("cv_extracted")
            or st.session_state.get("experience")
            or st.session_state.get("original_cv_files")
        ) else 0
        total_versions = original_count + len(cv_versions)
        st.metric("Resume Versions", total_versions)
        st.caption("Available CVs")

with k2:
    with st.container():
        avg_ats = "—"
        if ats_history:
            scores = [a.get("score", 0) for a in ats_history if a.get("score")]
            if scores:
                avg_ats = f"{sum(scores)//len(scores)}%"
        st.metric("ATS Average", avg_ats)
        st.caption("From previous analyses")

with k3:
    with st.container():
        st.metric("Applications", len(applications) if applications else 0)
        st.caption("Total tracked")

with k4:
    with st.container():
        st.metric("Profile", f"{completion}%")
        st.caption("Completion rate")

st.markdown("---")

# ──────────────────────────────────────────────
# 3. ACTIVITY CENTER
# ──────────────────────────────────────────────
st.subheader("Activity Center")

left, right = st.columns([1, 1])

with left:
    st.markdown("#### 🟢 Recommended Actions")
    st.markdown("""
- Analyze a new Job Description  
- Update your main Resume (+3 ATS potential)  
- Complete missing References section  
- Add Languages & Certifications  
    """)
    if st.button("Start Recommended Action", type="primary", use_container_width=True):
        st.info("→ Please click **ATS Analyzer** in the left sidebar.")

with right:
    st.markdown("#### Recent Activity")
    if ats_history:
        for item in ats_history[:3]:
            st.success(f"✓ ATS Analysis completed — {item.get('job_title', 'Job')} · Score: {item.get('score', '—')}%")
    else:
        st.info("No recent activity yet. Run your first ATS analysis to get started.")

st.markdown("---")

# ──────────────────────────────────────────────
# 4. QUICK ACTIONS
# ──────────────────────────────────────────────
st.subheader("Quick Actions")

qa1, qa2, qa3 = st.columns(3)

with qa1:
    with st.container():
        st.markdown("### Analyze Job")
        st.caption("Start a new ATS analysis")
        if st.button("Open ATS Analyzer", key="qa_ats", use_container_width=True, type="primary"):
            st.info("→ Please click **ATS Analyzer** in the left sidebar.")

with qa2:
    with st.container():
        st.markdown("### Resume Center")
        st.caption("Manage CV versions")
        if st.button("Open Resume Center", key="qa_resume", use_container_width=True):
            st.info("Document Engine coming in the next stage.")

with qa3:
    with st.container():
        st.markdown("### My Profile")
        st.caption("Update experience, skills and certificates")
        if st.button("Manage Profile", key="qa_profile", use_container_width=True):
            st.info("→ Please click **profile** in the left sidebar.")

st.markdown("---")

# ──────────────────────────────────────────────
# 5. APPLICATION SUMMARY
# ──────────────────────────────────────────────
st.subheader("Applications")

a1, a2, a3, a4 = st.columns(4)
with a1:
    st.metric("Applied", 0)
with a2:
    st.metric("Pending", 0)
with a3:
    st.metric("Interview", 0)
with a4:
    st.metric("Rejected", 0)

st.caption("Application Tracker will populate these numbers automatically.")
st.markdown("---")

# ──────────────────────────────────────────────
# 6. RESUME SNAPSHOT
# ──────────────────────────────────────────────
st.subheader("Resume Snapshot")

original_files = st.session_state.get("original_cv_files", [])

if original_files:
    f = original_files[0]
    st.markdown(f"### 📄 {f.get('original_name', 'Original CV')}")
    st.caption(f"Uploaded: {str(f.get('uploaded_at', ''))[:10]} • {f.get('size_kb', '?')} KB")

    # New logic: use base64 if available (permanent storage)
    if f.get("content_base64"):
        import base64
        file_bytes = base64.b64decode(f["content_base64"])
        mime = f.get("mime", "application/pdf")

        st.download_button(
            label="👁 View / Download Original CV",
            data=file_bytes,
            file_name=f.get("original_name", "original_cv.pdf"),
            mime=mime,
            key="view_original_cv_btn",
            use_container_width=True
        )

        # Optional PDF preview
        if mime == "application/pdf" or str(f.get("original_name", "")).lower().endswith(".pdf"):
            with st.expander("Preview CV", expanded=False):
                base64_pdf = f["content_base64"]
                pdf_display = f'''
                    <iframe
                        src="data:application/pdf;base64,{base64_pdf}"
                        width="100%"
                        height="700"
                        type="application/pdf"
                        style="border: 1px solid #334155; border-radius: 8px;">
                    </iframe>
                '''
                st.markdown(pdf_display, unsafe_allow_html=True)
    else:
        st.warning("File is registered but no permanent content found.")
        st.caption("Please go to **Profile → Update Mode** and re-upload the CV to store it permanently.")

    st.info("To upload a **new** original CV, go to **Profile → Update Mode**.")
else:
    st.info("No original CV stored yet.")
    st.markdown("To add your original CV, go to **Profile → Update Mode**.")
# ──────────────────────────────────────────────
# 7. FOOTER
# ──────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    st.caption("AIROS v2.1")
with col_f2:
    st.caption("Database: Connected")
with col_f3:
    st.caption(f"Last Login: {datetime.now().strftime('%d %b %Y')}")

st.caption("Support: support@airos.internal")