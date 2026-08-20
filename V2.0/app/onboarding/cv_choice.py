import streamlit as st
import os
from datetime import datetime
from services.cv_extractor import extract_rich_profile
from services.profile_service import save_user_profile

def _save_original_cvs(uploaded_files, user_email: str) -> list:
    """
    Save the original uploaded CVs permanently on disk.
    Returns a list of metadata about the saved files.
    """
    if not user_email:
        user_email = "anonymous"

    # Clean email for folder name
    safe_email = user_email.replace("@", "_at_").replace(".", "_")
    upload_dir = os.path.join("data", "uploads", safe_email)
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []

    for idx, uploaded_file in enumerate(uploaded_files, start=1):
        # Keep original extension
        ext = os.path.splitext(uploaded_file.name)[1].lower() or ".pdf"
        filename = f"original_cv_{idx}{ext}"
        filepath = os.path.join(upload_dir, filename)

        # Write the binary content
        with open(filepath, "wb") as f:
            f.write(uploaded_file.getbuffer())

        saved_files.append({
            "original_name": uploaded_file.name,
            "saved_as": filename,
            "path": filepath,
            "uploaded_at": datetime.utcnow().isoformat(),
            "size_kb": round(len(uploaded_file.getbuffer()) / 1024, 1)
        })

    return saved_files


def render_cv_choice():
    st.title("Welcome to AIROS")
    st.subheader("How do you want to build your professional identity?")
    st.caption("You can always enrich or edit your profile later.")
    st.markdown("---")

    col1, col2 = st.columns(2, gap="large")

    # ──────────────────────────────────────────────
    # ROAD A – Manual
    # ──────────────────────────────────────────────
    with col1:
        st.markdown("### ✍️ Manual Mode")
        st.write("You will fill all information yourself step by step.")
        st.write("")
        if st.button("Continue with Manual Mode", use_container_width=True, type="primary", key="btn_manual"):
            st.session_state.profile_method = "manual"
            st.session_state.cv_extracted = None
            st.session_state.uploaded_cvs = []
            st.session_state.original_cv_files = []
            st.session_state.onboarding_step = "career_stage"
            st.rerun()

    # ──────────────────────────────────────────────
    # ROAD B – AI Powered
    # ──────────────────────────────────────────────
    with col2:
        st.markdown("### 🤖 AI-Powered Mode")
        st.write("Upload one or several CVs. AIROS will extract the data and pre-fill the forms.")

        uploaded_files = st.file_uploader(
            "Upload your CV(s) (PDF or DOCX)",
            type=["pdf", "docx"],
            accept_multiple_files=True,
            key="cv_uploader"
        )

        if uploaded_files:
            st.success(f"{len(uploaded_files)} file(s) selected")
            for f in uploaded_files:
                st.caption(f"• {f.name}")

        extract_btn = st.button(
            "Extract with AIROS & Continue",
            use_container_width=True,
            type="primary",
            key="btn_ai",
            disabled=not uploaded_files
        )

        if extract_btn and uploaded_files:
            with st.spinner("AIROS is analyzing your CV(s)... This may take a moment"):
                rich_data = extract_rich_profile(uploaded_files)

            if rich_data:
                # 1. Save the original files permanently
                user_email = st.session_state.get("user", "anonymous")
                saved_files = _save_original_cvs(uploaded_files, user_email)

                # 2. Store everything in session
                st.session_state.profile_method = "ai"
                st.session_state.cv_extracted = rich_data
                st.session_state.uploaded_cvs = uploaded_files          # temporary
                st.session_state.original_cv_files = saved_files        # permanent record

                # 2b. Populate skills & languages immediately so they survive early saves
                if rich_data.get("skills") and isinstance(rich_data["skills"], dict):
                    st.session_state.skills = rich_data["skills"]
                elif rich_data.get("technical_skills") or rich_data.get("core_skills"):
                    st.session_state.skills = {
                        "technical": rich_data.get("technical_skills", []),
                        "core": rich_data.get("core_skills", []),
                        "methodologies": [],
                        "tools": [],
                    }

                if rich_data.get("languages") and isinstance(rich_data["languages"], list):
                    st.session_state.languages = rich_data["languages"]

                if rich_data.get("certifications") and isinstance(rich_data["certifications"], list):
                    st.session_state.certifications = rich_data["certifications"]

                # 3. Persist to users_db.json
                save_user_profile()

                st.session_state.onboarding_step = "career_stage"
                st.rerun()
            else:
                st.error("Extraction failed. Please try again or use Manual Mode.")

    st.markdown("---")
    st.caption("You can upload multiple versions of your CV. AIROS will combine them to build the richest possible profile.")