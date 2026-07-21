import sys
from pathlib import Path

# Add project root directory (.../AIROS) to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from database.crud import save_master_cv, get_latest_master_cv
from utils.nav import render_sidebar

st.set_page_config(page_title="AIROS - CV Manager", page_icon="📄", layout="wide")

render_sidebar()

st.title("📄 Master CV Manager")
st.markdown("Store and maintain your core Master CV text to serve as the baseline for ATS tailoring.")

current_cv = get_latest_master_cv()

if current_cv:
    st.success(f"✅ Active Master CV Loaded: **{current_cv['title']}** (Target Role: {current_cv['target_role'] or 'N/A'})")

st.subheader("📝 Update Baseline Master CV")

with st.form("master_cv_form"):
    title = st.text_input("CV Profile Title", value=current_cv['title'] if current_cv else "Master CV - Senior IT Program Manager")
    target_role = st.text_input("Target Role Category", value=current_cv['target_role'] if current_cv else "ERP Program / Project Manager")
    raw_text = st.text_area("Master CV Plain Text", value=current_cv['raw_text'] if current_cv else "", height=350, placeholder="Paste complete baseline CV text here...")

    submitted = st.form_submit_button("💾 Save Master CV")

    if submitted:
        if not title or not raw_text:
            st.error("Please fill in both the CV Title and CV Text fields.")
        else:
            cv_id = save_master_cv(title=title, target_role=target_role, raw_text=raw_text)
            st.success(f"✅ Master CV updated successfully (ID: {cv_id})!")
            st.rerun()