import streamlit as st
import difflib

CAREER_STAGES = [
    "Student / Recent Graduate",
    "Looking for Internship",
    "Entry-Level Professional (0–2 years)",
    "Experienced Professional (3–8 years)",
    "Senior Expert / Manager (8+ years)",
    "Freelancer / Consultant",
    "Entrepreneur / Business Owner",
    "Career Transition / Changing Path"
]


def _normalize_career_stage(suggestion: str) -> str | None:
    """Try exact match first, then fuzzy match."""
    if not suggestion:
        return None
    suggestion = suggestion.strip()
    if suggestion in CAREER_STAGES:
        return suggestion
    # Fuzzy fallback
    match = difflib.get_close_matches(suggestion, CAREER_STAGES, n=1, cutoff=0.55)
    return match[0] if match else None


def render_career_stage():
    st.title("Welcome to AIROS")
    st.subheader("Let's build your professional identity")
    st.markdown("This helps us personalize your experience and give you better recommendations.")
    st.markdown("---")
    st.markdown("### What best describes your current situation?")

    # Pre-select from AI extraction if available
    default_index = None
    if st.session_state.get("profile_method") == "ai" and st.session_state.get("cv_extracted"):
        suggestion = st.session_state.cv_extracted.get("career_stage_suggestion", "")
        normalized = _normalize_career_stage(suggestion)
        if normalized:
            default_index = CAREER_STAGES.index(normalized)
            st.info(f"AI suggestion: **{normalized}** (you can change it)")

    selected_stage = st.radio(
        label="Select your career stage",
        options=CAREER_STAGES,
        index=default_index,
        label_visibility="collapsed"
    )

    st.markdown("")
    col1, col2, col3 = st.columns([1, 1, 2])
    with col2:
        continue_btn = st.button(
            "Continue →",
            type="primary",
            use_container_width=True,
            disabled=selected_stage is None
        )

    if continue_btn and selected_stage:
        st.session_state.career_stage = selected_stage
        st.session_state.onboarding_step = "personal_identity"
        st.rerun()