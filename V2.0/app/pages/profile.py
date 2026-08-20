import sys
from pathlib import Path

# Fix Python path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st
import os
import base64
from datetime import datetime
from services.cv_extractor import extract_rich_profile
from services.session_manager import initialize_session, require_auth, logout
from services.profile_service import save_user_profile, load_user_profile

# ──────────────────────────────────────────────
# Page Config + Sidebar cleaning
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="AIROS – Profile",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
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
# Auth guard
# ──────────────────────────────────────────────
initialize_session()
require_auth()

# Load profile if needed
if "personal_identity" not in st.session_state:
    load_user_profile()

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

def calculate_profile_completeness() -> int:
    score = 0
    identity = st.session_state.get("personal_identity", {})
    if isinstance(identity, dict) and (identity.get("first_name") or identity.get("full_name")):
        score += 15
    if st.session_state.get("education"):
        score += 20
    if st.session_state.get("experience"):
        score += 25
    if st.session_state.get("skills"):
        score += 20
    if st.session_state.get("languages"):
        score += 10
    if st.session_state.get("certifications"):
        score += 10
    return min(score, 100)

def deduplicate_list(data_list):
    """Remove exact duplicates while preserving order"""
    if not data_list:
        return []
    seen = set()
    unique = []
    for item in data_list:
        key = str(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

# ──────────────────────────────────────────────
# Mode initialization
# ──────────────────────────────────────────────
if "profile_mode" not in st.session_state:
    st.session_state.profile_mode = "review"

# ──────────────────────────────────────────────
# Header + Mode Switcher
# ──────────────────────────────────────────────
st.title("👤 Master Profile")

col_user, col_logout = st.columns([5, 1])
with col_user:
    st.markdown(f"**Logged in as:** {get_user_name()}")
with col_logout:
    if st.button("Logout", use_container_width=True):
        logout()
        st.switch_page("main.py")

st.markdown("---")

# Mode switcher
st.markdown("### Choose Mode")
mode_col1, mode_col2 = st.columns(2)
with mode_col1:
    if st.button(
        "👁 Review Mode (Read-only)",
        use_container_width=True,
        type="primary" if st.session_state.get("profile_mode") == "review" else "secondary"
    ):
        st.session_state.profile_mode = "review"
        st.rerun()
with mode_col2:
    if st.button(
        "✏️ Update Mode (Edit)",
        use_container_width=True,
        type="primary" if st.session_state.get("profile_mode") == "update" else "secondary"
    ):
        st.session_state.profile_mode = "update"
        st.rerun()

current_mode = st.session_state.get("profile_mode", "review")
if current_mode == "review":
    st.info("You are currently in **Review Mode** — all fields are locked.")
else:
    st.warning("You are currently in **Update Mode** — you can edit the data and replace the Original CV.")

st.markdown("---")

# Profile strength
completeness = calculate_profile_completeness()
st.progress(completeness / 100)
st.markdown(f"**Profile strength: {completeness}%**")
if completeness < 80:
    st.info("Complete the missing sections to reach 100% and improve your matching score.")
else:
    st.success("Your profile is strong.")

st.markdown("---")

# Mode flags
is_review = st.session_state.profile_mode == "review"
is_update = st.session_state.profile_mode == "update"

# ──────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "Personal Info",
    "Experience & Education",
    "Skills & Languages",
    "Original CV"
])

# ========== TAB 1: Personal Info ==========
with tab1:
    st.subheader("Personal Information")
    identity = st.session_state.get("personal_identity", {})
    if not isinstance(identity, dict):
        identity = {}

    full_name = (
        identity.get("full_name")
        or f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
    )
    email = identity.get("email") or st.session_state.get("user", "")
    location = (
        identity.get("location")
        or f"{identity.get('city', '')}, {identity.get('country', '')}".strip(", ")
    )
    linkedin = identity.get("linkedin") or identity.get("linkedin_url", "")
    phone = identity.get("phone") or identity.get("whatsapp", "")
    summary = identity.get("summary", "")

    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Full Name", value=full_name, disabled=is_review, key="p_full_name")
        st.text_input("Email", value=email, disabled=is_review, key="p_email")
    with col2:
        st.text_input("Location", value=location, disabled=is_review, key="p_location")
        st.text_input("LinkedIn", value=linkedin, disabled=is_review, key="p_linkedin")

    st.text_input("Phone", value=phone, disabled=is_review, key="p_phone")
    st.text_area("Professional Summary", value=summary, height=120, disabled=is_review, key="p_summary")

# ========== TAB 2: Experience & Education ==========
with tab2:
    st.subheader("Professional Experience & Education")

    experience = deduplicate_list(st.session_state.get("experience", []))
    education = deduplicate_list(st.session_state.get("education", []))

    if experience:
        st.markdown("**Experience**")
        for exp in experience[:15]:
            if isinstance(exp, dict):
                title = exp.get("title") or exp.get("role") or "Role"
                company = exp.get("company") or exp.get("organization") or ""
                st.write(f"• **{title}** at {company}")
            else:
                st.write(f"• {exp}")
    else:
        st.info("No experience recorded yet.")

    st.markdown("---")

    if education:
        st.markdown("**Education**")
        for edu in education:
            if isinstance(edu, dict):
                degree = edu.get("degree") or edu.get("title") or ""
                institution = edu.get("institution") or edu.get("school") or ""
                st.write(f"• {degree} — {institution}")
            else:
                st.write(f"• {edu}")
    else:
        st.info("No education recorded yet.")

    if is_update:
        st.info("Full experience/education editing will be available in the next iteration. For now you can update Personal Info and Original CV.")

# ========== TAB 3: Skills & Languages ==========
with tab3:
    st.subheader("Skills & Languages")

    skills = st.session_state.get("skills", {})
    if not isinstance(skills, dict):
        skills = {}

    tech = skills.get("technical", []) or []
    methods = skills.get("methodologies", []) or []
    tools = skills.get("tools", []) or []
    core = skills.get("core", []) or []

    # Fallback: if the structured skills are empty, try the flat lists from extraction
    if not any([tech, methods, tools, core]):
        tech = st.session_state.get("technical_skills", []) or []
        core = st.session_state.get("core_skills", []) or []

    st.markdown("**Technical Skills**")
    st.write(", ".join(tech) if tech else "—")

    st.markdown("**Core Skills**")
    st.write(", ".join(core) if core else "—")

    st.markdown("**Methodologies**")
    st.write(", ".join(methods) if methods else "—")

    st.markdown("**Tools & ERPs**")
    st.write(", ".join(tools) if tools else "—")

    st.markdown("---")

    languages = st.session_state.get("languages", [])
    if not languages:
        # Fallback from cv_extracted if present
        cv_data = st.session_state.get("cv_extracted", {})
        if isinstance(cv_data, dict):
            languages = cv_data.get("languages", [])

    if languages:
        st.markdown("**Languages**")
        for lang in languages:
            if isinstance(lang, dict):
                st.write(f"• {lang.get('language', '')} ({lang.get('level', '')})")
            else:
                st.write(f"• {lang}")
    else:
        st.write("No languages recorded.")

# ========== TAB 4: Original CV ==========
with tab4:
    st.subheader("Original CV")

    original_files = st.session_state.get("original_cv_files", [])

    if original_files:
        st.success(f"**{len(original_files)} original file(s) stored**")
        for f in original_files:
            st.write(f"• **{f.get('original_name', 'CV')}** — uploaded {str(f.get('uploaded_at', ''))[:10]} — {f.get('size_kb', '?')} KB")

    # REVIEW MODE → Download + Preview
    if is_review:
        st.markdown("### View / Download Original CV")
        for idx, f in enumerate(original_files):
            if f.get("content_base64"):
                file_bytes = base64.b64decode(f["content_base64"])
                file_name = f.get("original_name", "CV.pdf")
                mime = f.get("mime", "application/pdf")

                st.download_button(
                    label=f"📄 Download — {file_name}",
                    data=file_bytes,
                    file_name=file_name,
                    mime=mime,
                    key=f"download_cv_{idx}",
                    use_container_width=True
                )

                if mime == "application/pdf" or file_name.lower().endswith(".pdf"):
                    st.markdown("#### Preview")
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
                st.warning(f"No permanent content found for {f.get('original_name')}")
                st.caption("Please re-upload the CV in Update mode.")

    # UPDATE MODE → Upload / Replace + FULL AI RE-EXTRACTION
    if is_update:
        st.markdown("### Replace / Upload Original CV")
        st.caption("Uploading a new CV will re-extract **all** profile data (Personal Info, Experience, Education, Skills, Languages, Certifications).")

        new_file = st.file_uploader(
            "Upload Original CV (PDF or DOCX)",
            type=["pdf", "docx"],
            key="replace_original_cv"
        )

        if new_file is not None:
            if st.button("Save Original CV & Re-extract Profile", type="primary", use_container_width=True):
                # 1. Save the original file permanently
                file_bytes = new_file.getvalue()
                content_base64 = base64.b64encode(file_bytes).decode("utf-8")
                ext = os.path.splitext(new_file.name)[1].lower() or ".pdf"

                st.session_state.original_cv_files = [{
                    "original_name": new_file.name,
                    "saved_as": f"original_cv_1{ext}",
                    "uploaded_at": datetime.utcnow().isoformat(),
                    "size_kb": round(len(file_bytes) / 1024, 1),
                    "content_base64": content_base64,
                    "mime": "application/pdf" if ext == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                }]

                # 2. Run full AI extraction
                new_file.seek(0)
                with st.spinner("Re-extracting full profile from the new CV…"):
                    extracted = extract_rich_profile([new_file])

                # DEBUG — temporary: show what extraction returned
                with st.expander("🔍 DEBUG: Extraction result (remove later)", expanded=True):
                    st.write(f"Type: {type(extracted)}, Keys: {list(extracted.keys()) if isinstance(extracted, dict) else 'N/A'}")
                    if isinstance(extracted, dict):
                        st.write(f"skills: {extracted.get('skills')}")
                        st.write(f"technical_skills: {extracted.get('technical_skills')}")
                        st.write(f"languages: {extracted.get('languages')}")

                if not extracted:
                    st.error("Extraction failed. The original CV was saved, but profile data was not updated.")
                else:
                    # 3. Overwrite session_state with the new rich data (CORRECT KEYS)
                    if extracted.get("personal_identity"):
                        st.session_state.personal_identity = extracted["personal_identity"]

                    if extracted.get("education"):
                        st.session_state.education = extracted["education"]

                    # Experience – correct key from extractor
                    if extracted.get("professional_experience"):
                        st.session_state.experience = extracted["professional_experience"]

                    # Skills – combine technical + core
                    if extracted.get("skills") and isinstance(extracted["skills"], dict):
                        st.session_state.skills = extracted["skills"]
                        # also keep core if present
                        if extracted.get("core_skills"):
                            st.session_state.skills["core"] = extracted["core_skills"]
                    else:
                        # fallback to flat lists
                        tech = extracted.get("technical_skills") or []
                        core = extracted.get("core_skills") or []
                        st.session_state.skills = {
                            "technical": tech,
                            "core": core,
                            "methodologies": [],
                            "tools": []
                        }

                    if extracted.get("languages"):
                        st.session_state.languages = extracted["languages"]

                    if extracted.get("certifications"):
                        st.session_state.certifications = extracted["certifications"]

                    if extracted.get("total_experience_years") is not None:
                        st.session_state.total_experience_years = extracted["total_experience_years"]

                    if extracted.get("career_stage_suggestion"):
                        st.session_state.career_stage = extracted["career_stage_suggestion"]

                    # Clear old prefill flags
                    for flag in ["_skills_prefilled", "_languages_prefilled", "_education_prefilled", "_experience_prefilled"]:
                        if flag in st.session_state:
                            del st.session_state[flag]

                    # 4. Persist everything
                    save_user_profile()
                    st.success("✅ Original CV saved and full profile re-extracted successfully!")
                    st.session_state.profile_mode = "review"
                    st.rerun()

# Save button (only in Update mode)
if is_update:
    st.markdown("---")
    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        save_user_profile()
        st.success("Profile updated successfully!")
        st.session_state.profile_mode = "review"
        st.rerun()