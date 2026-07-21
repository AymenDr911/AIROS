import streamlit as st
from database.crud import get_master_cv, get_all_jobs, save_custom_cv
from utils.ats import calculate_ats_gap
from utils.nav import render_sidebar

st.set_page_config(page_title="ATS Analyzer - AIROS", page_icon="🎯", layout="wide")
render_sidebar()

st.title("🎯 3-Phase ATS Gap Analyzer")
st.caption("Run structured gap reports on target job postings against your Master CV.")

# Retrieve data from SQLite Database
master_cv = get_master_cv()
jobs = get_all_jobs()

if not master_cv:
    st.warning("⚠️ No Master CV found in database! Please save a Master CV in CV Manager first.")
    st.stop()

if not jobs:
    st.warning("⚠️ No Job listings found! Please add a job offer in the Jobs section first.")
    st.stop()

# Dropdown to select job offer
job_options = {f"{j['title']} @ {j['company']} (ID: {j['id']})": j for j in jobs}
selected_job_label = st.selectbox("Select Target Job Offer:", list(job_options.keys()))
selected_job = job_options[selected_job_label]

if st.button("🚀 Run 3-Phase ATS Diagnostic Report", type="primary"):
    # Calls the updated calculate_ats_gap from utils/ats.py
    results = calculate_ats_gap(master_cv['raw_text'], selected_job['description'])
    
    st.session_state['ats_results'] = results
    st.session_state['selected_job_id'] = selected_job['id']

if 'ats_results' in st.session_state:
    results = st.session_state['ats_results']
    
    st.markdown("---")
    st.subheader("📊 Phase 1: Strategic Match Score")
    col1, col2, col3 = st.columns(3)
    col1.metric("Overall ATS Score", f"{results['ats_score']}%")
    col2.metric("Exact Keyword Hits", len(results['hits']))
    col3.metric("Keyword Gaps Identified", len(results['gaps']))

    st.progress(results['ats_score'] / 100.0)

    st.markdown("---")
    st.subheader("🧩 Phase 2: Competency Gap Matrix")
    col_hits, col_gaps = st.columns(2)

    with col_hits:
        st.markdown("### ✅ Verified Keywords in CV")
        st.write(", ".join([f"`{w}`" for w in results['hits']]) if results['hits'] else "None")

    with col_gaps:
        st.markdown("### ⚠️ Critical Keyword Gaps")
        st.write(", ".join([f"`{w}`" for w in results['gaps']]) if results['gaps'] else "None")