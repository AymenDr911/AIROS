import streamlit as st
from app.onboarding.cv_choice import render_cv_choice
from app.onboarding.career_stage import render_career_stage
from app.onboarding.personal_identity import render_personal_identity
from app.onboarding.education import render_education
from app.onboarding.experience import show_experience
from app.onboarding.skills import show_skills

st.set_page_config(
    page_title="AIROS V2 - Onboarding",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Hide sidebar completely
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarNav"] {display: none;}
        section[data-testid="stSidebar"] {display: none !important;}
    </style>
""", unsafe_allow_html=True)


def main():
    # Protect the page
    if not st.session_state.get("logged_in", False) or "user" not in st.session_state:
        st.switch_page("main.py")
        st.stop()

    # Default first step
    if "onboarding_step" not in st.session_state:
        st.session_state.onboarding_step = "cv_choice"

    step = st.session_state.onboarding_step

    # ---------- ROUTER ----------
    if step == "cv_choice":
        render_cv_choice()
    elif step == "career_stage":
        render_career_stage()
    elif step == "personal_identity":
        render_personal_identity()
    elif step == "education":
        render_education()
    elif step == "experience":
        show_experience()
    elif step == "skills":
        show_skills()
    else:
        st.session_state.onboarding_step = "cv_choice"
        st.rerun()


if __name__ == "__main__":
    main()
