import streamlit as st
from services.profile_service import save_user_profile

def show_skills():
    st.title("Skills & Competencies")
    st.markdown("Add your core professional skills, methodologies, and tools to optimize your ATS profile matching.")
    st.markdown("---")
    st.caption("Step 5 of 9 — Skills")
    st.progress(50)

    # -------------------------------------------------
    # Initialize
    # -------------------------------------------------
    if "skills" not in st.session_state:
        st.session_state.skills = {
            "technical": [],
            "methodologies": [],
            "tools": []
        }

    # -------------------------------------------------
    # Pre-fill only once from AI extraction
    # -------------------------------------------------
    if (
        st.session_state.get("profile_method") == "ai"
        and st.session_state.get("cv_extracted")
        and not st.session_state.get("_skills_prefilled")
    ):
        ai_skills = st.session_state.cv_extracted.get("skills")

        if isinstance(ai_skills, dict):
            st.session_state.skills["technical"] = ai_skills.get("technical", []) or []
            st.session_state.skills["methodologies"] = ai_skills.get("methodologies", []) or []
            st.session_state.skills["tools"] = ai_skills.get("tools", []) or []
        elif isinstance(ai_skills, list):
            # fallback: put everything in technical
            st.session_state.skills["technical"] = [str(s).strip() for s in ai_skills if str(s).strip()]

        st.session_state._skills_prefilled = True

        total = (
            len(st.session_state.skills["technical"])
            + len(st.session_state.skills["methodologies"])
            + len(st.session_state.skills["tools"])
        )
        if total > 0:
            st.info(f"{total} skill entries pre-filled from your CV.")

    # -------------------------------------------------
    # Edit mode flag
    # -------------------------------------------------
    if "skills_editing" not in st.session_state:
        st.session_state.skills_editing = False

    is_editing = st.session_state.skills_editing

    # -------------------------------------------------
    # Form
    # -------------------------------------------------
    st.markdown("### Core Competencies")

    # We use session_state keys so the values persist correctly
    if "skills_tech_input" not in st.session_state:
        st.session_state.skills_tech_input = ", ".join(st.session_state.skills.get("technical", []))
    if "skills_method_input" not in st.session_state:
        st.session_state.skills_method_input = ", ".join(st.session_state.skills.get("methodologies", []))
    if "skills_tools_input" not in st.session_state:
        st.session_state.skills_tools_input = ", ".join(st.session_state.skills.get("tools", []))

    tech_input = st.text_input(
        "Technical Languages & Frameworks (comma-separated)",
        placeholder="e.g. Python, SQL, JavaScript",
        disabled=not is_editing,
        key="skills_tech_input"
    )

    method_input = st.text_input(
        "Methodologies & Management",
        placeholder="e.g. Agile, Scrum, Kanban, PMP",
        disabled=not is_editing,
        key="skills_method_input"
    )

    tools_input = st.text_input(
        "Enterprise Software & Tools",
        placeholder="e.g. Odoo, SAP, Jira, Confluence, Git",
        disabled=not is_editing,
        key="skills_tools_input"
    )

    # -------------------------------------------------
    # Edit / Save / Cancel
    # -------------------------------------------------
    if not is_editing:
        if st.button("✏️ Edit Skills", use_container_width=True):
            st.session_state.skills_editing = True
            st.rerun()
    else:
        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("💾 Save Skills", use_container_width=True, type="primary"):
                st.session_state.skills["technical"] = [s.strip() for s in tech_input.split(",") if s.strip()]
                st.session_state.skills["methodologies"] = [s.strip() for s in method_input.split(",") if s.strip()]
                st.session_state.skills["tools"] = [t.strip() for t in tools_input.split(",") if t.strip()]
                st.session_state.skills_editing = False
                st.success("Skills updated successfully!")
                st.rerun()
        with col_cancel:
            if st.button("Cancel", use_container_width=True):
                # Restore original values
                st.session_state.skills_tech_input = ", ".join(st.session_state.skills.get("technical", []))
                st.session_state.skills_method_input = ", ".join(st.session_state.skills.get("methodologies", []))
                st.session_state.skills_tools_input = ", ".join(st.session_state.skills.get("tools", []))
                st.session_state.skills_editing = False
                st.rerun()

    # -------------------------------------------------
    # Navigation
    # -------------------------------------------------
    st.markdown("---")
    col_btn1, col_btn2 = st.columns([1, 2])

    with col_btn1:
        if st.button("← Back"):
            st.session_state.onboarding_step = "experience"
            st.rerun()

    with col_btn2:
        if st.button("Finish & Go to Profile →", type="primary", use_container_width=True):
            # Persist any pending edits
            if st.session_state.get("skills_editing", False):
                st.session_state.skills["technical"] = [s.strip() for s in tech_input.split(",") if s.strip()]
                st.session_state.skills["methodologies"] = [s.strip() for s in method_input.split(",") if s.strip()]
                st.session_state.skills["tools"] = [t.strip() for t in tools_input.split(",") if t.strip()]
                st.session_state.skills_editing = False

            # Mark onboarding as finished
            st.session_state.onboarding_completed = True
            st.session_state.onboarding_step = "done"

            save_user_profile()

            # Go to Master Profile
            st.switch_page("pages/profile.py")