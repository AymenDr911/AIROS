import sys
from pathlib import Path

# Add parent directory to path
app_dir = Path(__file__).resolve().parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

import streamlit as st
from utils.ats import calculate_ats_gap, build_candidate_json
from utils.job import save_job, add_contact_to_job
from utils.company import find_or_create_company


# ------------------------------------------------------------------
# Helper function - Render Save Section
# ------------------------------------------------------------------
def _render_save_section(result: dict, job_text: str, parsed: dict):
    """Display Company card + Recruiter form + Save button."""
    st.markdown("### Company & Recruiter")
    
    # ---------- Company Card ----------
    with st.container(border=True):
        st.markdown("#### 🏢 Company")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Name**\n{parsed.get('company_name') or '—'}")
        c2.markdown(f"**City / Location**\n{parsed.get('city') or parsed.get('location') or '—'}")
        c3.markdown(f"**Country**\n{parsed.get('country') or '—'}")
        
        c4, c5, c6 = st.columns(3)
        c4.markdown(f"**Address**\n{parsed.get('address') or '—'}")
        c5.markdown(f"**Industry**\n{parsed.get('industry') or '—'}")
        c6.markdown(f"**Phone**\n{parsed.get('company_phone') or '—'}")
        
        c7, c8 = st.columns(2)
        c7.markdown(f"**Website**\n{parsed.get('company_website') or '—'}")
        c8.markdown(f"**LinkedIn**\n{parsed.get('company_linkedin') or '—'}")
    
    # ---------- Recruiter / Contact Form ----------
    st.markdown("#### 👤 Recruiter / Contact")
    st.caption(
        "Add the individual recruiter if known. "
        "Generic emails (info@, careers@, jobs@…) are automatically treated as low-confidence."
    )
    
    with st.form("recruiter_form", clear_on_submit=True):
        r1, r2 = st.columns(2)
        
        with r1:
            rec_name = st.text_input("Name", placeholder="Anna Müller", key="rec_name_input")
            rec_position = st.text_input("Position", placeholder="Senior Talent Acquisition", key="rec_position_input")
            rec_email = st.text_input("Email", placeholder="anna.mueller@company.com", key="rec_email_input")
        
        with r2:
            rec_linkedin = st.text_input("LinkedIn URL", placeholder="https://linkedin.com/in/...", key="rec_linkedin_input")
            rec_type = st.selectbox(
                "Contact Type",
                ["HR Recruiter", "Talent Acquisition", "Hiring Manager", "General"],
                key="rec_type_input",
            )
            rec_confidence = st.selectbox("Confidence", ["High", "Medium", "Low"], index=1, key="rec_confidence_input")
        
        save_clicked = st.form_submit_button(
            "💾 Save Job + Company + Recruiter", 
            type="primary", 
            use_container_width=True
        )
        
        if save_clicked:
            # 1. Save Job (also creates/reuses Company)
            saved_job = save_job(
                analysis_result=result,
                original_jd=job_text,
                job_title=parsed.get("job_title", ""),
                company_name=parsed.get("company_name", ""),
                location=parsed.get("location", ""),
                country=parsed.get("country", ""),
                source="Manual paste",
            )
            
            # 2. Save recruiter contact info to session for Job Application page
            if rec_name.strip() or rec_email.strip():
                if 'job_contacts' not in st.session_state:
                    st.session_state['job_contacts'] = {}
                
                st.session_state['job_contacts'][saved_job['job_id']] = {
                    'name': rec_name.strip(),
                    'position': rec_position.strip(),
                    'email': rec_email.strip(),
                    'linkedin_url': rec_linkedin.strip(),
                    'contact_type': rec_type,
                    'confidence': rec_confidence,
                    'source': 'Manual',
                }
            
            # 3. Optionally create & link Contact in database
            contact_msg = ""
            if rec_name.strip():
                contact = add_contact_to_job(
                    job_id=saved_job["job_id"],
                    name=rec_name,
                    position=rec_position,
                    email=rec_email,
                    linkedin_url=rec_linkedin,
                    contact_type=rec_type,
                    confidence=rec_confidence,
                    source="Manual",
                )
                if contact:
                    contact_msg = f" + Contact **{contact['contact_id']}**"
            
            st.success(
                f"✅ Successfully saved → Job **{saved_job['job_id']}** "
                f"(Company **{saved_job['company_id']}**){contact_msg}"
            )
            st.balloons()
            st.info("➡️ You can now move to the **Job Application** page.")
            
            # Force navigation refresh
            st.rerun()


# ------------------------------------------------------------------
# Main Page Configuration
# ------------------------------------------------------------------
st.set_page_config(page_title="ATS Analyzer", page_icon="📄", layout="wide")
st.title("📄 ATS Resume Analyzer")
st.caption("Uses your existing AIROS profile (rich JSON) + Job Description")


# ------------------------------------------------------------------
# Load Existing Candidate Profile
# ------------------------------------------------------------------
candidate_profile = build_candidate_json()
has_profile = bool(
    candidate_profile.get("skills", {}).get("technical")
    or candidate_profile.get("experience")
    or candidate_profile.get("total_experience_years", 0) > 0
    or candidate_profile.get("languages")
)

if has_profile:
    st.success("✅ Using your existing AIROS profile")
    with st.expander("Profile summary loaded", expanded=False):
        st.write({
            "Experience (years)": candidate_profile.get("total_experience_years"),
            "Technical skills": candidate_profile.get("skills", {}).get("technical", [])[:12],
            "Methodologies": candidate_profile.get("skills", {}).get("methodologies", [])[:8],
            "Tools": candidate_profile.get("skills", {}).get("tools", [])[:8],
            "Languages": candidate_profile.get("languages", []),
            "Location": candidate_profile.get("location"),
        })
else:
    st.warning("⚠️ No rich profile found in session yet. Please complete your Profile / Onboarding first.")


# ------------------------------------------------------------------
# Job Description Input
# ------------------------------------------------------------------
st.subheader("Job Description")
job_text = st.text_area(
    "Paste the full job description here",
    height=280,
    placeholder="Paste the complete job description...",
    label_visibility="collapsed",
)


# ------------------------------------------------------------------
# Analyze Button
# ------------------------------------------------------------------
if st.button("Analyze ATS Match", type="primary", use_container_width=True):
    if not job_text.strip():
        st.warning("Please paste a Job Description.")
    elif not has_profile:
        st.error("Cannot analyze without a profile. Please go to **Profile** or **Onboarding** first.")
    else:
        with st.spinner("Running advanced ATS analysis..."):
            result = calculate_ats_gap(
                cv_input=candidate_profile,
                job_text=job_text,
                force_job_refresh=False,
            )
        
        st.session_state["last_ats_result"] = result
        st.session_state["last_job_text"] = job_text
        # Reset any previous approval decision
        st.session_state.pop("manual_approval", None)


# ------------------------------------------------------------------
# Display Results
# ------------------------------------------------------------------
if "last_ats_result" in st.session_state:
    result = st.session_state["last_ats_result"]
    job_text = st.session_state.get("last_job_text", "")
    score = result.get("ats_score", 0)
    decision = result.get("decision", "N/A")
    parsed = result.get("parsed_job") or {}
    
    st.markdown("---")
    
    # Overall Score
    color = "green" if score >= 80 else "orange" if score >= 65 else "red"
    st.markdown(f"### Overall ATS Score: :{color}[{score}%] — **{decision}**")
    
    # Hard Blockers
    blockers = result.get("hard_blockers", [])
    if blockers:
        st.error("🚨 Hard Blockers Detected")
        for b, exp in zip(blockers, result.get("blocker_explanations", [])):
            st.markdown(f"**{b}**\n{exp}")
    
    # Sub-Scores
    with st.expander("Detailed Sub-Scores", expanded=True):
        sub = result.get("sub_scores", {})
        cols = st.columns(4)
        for i, (k, v) in enumerate(sub.items()):
            cols[i % 4].metric(k.replace("_", " ").title(), f"{v}%")
    
    # Strengths & Gaps
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("#### ✅ Strengths")
        hits = result.get("hits", [])
        if hits:
            st.success(", ".join(hits[:30]))
        else:
            st.info("No strong matches detected.")
    
    with col_b:
        st.markdown("#### ❌ Missing / Gaps")
        gaps = result.get("gaps", [])
        if gaps:
            st.warning(", ".join(gaps[:30]))
        else:
            st.info("No significant gaps detected.")
    
    # ------------------------------------------------------------------
    # Threshold Gated Section
    # ------------------------------------------------------------------
    st.markdown("---")
    
    # 1. Hard rejection (< 65)
    if score < 65:
        st.error(
            "### This job does not fit your current profile.\n\n"
            "I strongly recommend moving to other offers that are more aligned with your experience and skills."
        )
        st.info("💡 Tip: Look for roles closer to your strongest skills and experience level.")
    
    # 2. Soft rejection (65 – 74)
    elif score < 75:
        st.warning(
            "### This job is not yet suitable for your current profile.\n\n"
            "**AIROS recommendation:**"
        )
        st.markdown(
            """
            - Strengthen the missing skills shown above
            - Consider targeted training or certifications
            - Gain additional experience in the required areas
            
            Once your profile is stronger, you can re-analyse this offer.
            """
        )
    
    # 3. Manual approval gate (75 – 79)
    elif score < 80:
        st.info(
            "### Borderline match (75–79%)\n\n"
            "This role is close to your profile but not a clear strong match. "
            "Would you like to proceed and save it for further tracking?"
        )
        
        col_approve, col_cancel = st.columns(2)
        
        with col_approve:
            if st.button("✅ Approve & Continue", type="primary", use_container_width=True):
                st.session_state["manual_approval"] = True
                st.rerun()
        
        with col_cancel:
            if st.button("❌ Cancel", use_container_width=True):
                st.session_state.pop("last_ats_result", None)
                st.session_state.pop("last_job_text", None)
                st.session_state.pop("manual_approval", None)
                st.rerun()
        
        # Show save section only if approved
        if st.session_state.get("manual_approval") is True:
            _render_save_section(result, job_text, parsed)
    
    # 4. Strong match (≥ 80) → automatic rich path
    else:
        st.success(
            "### Strong match (≥ 80%)\n\n"
            "This role is well aligned with your profile. "
            "You can now review the company details and save the job."
        )
        _render_save_section(result, job_text, parsed)