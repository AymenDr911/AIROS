import streamlit as st
from database.db import init_db
from database.crud import save_master_cv, get_master_cv

# Page Configuration
st.set_page_config(page_title="AIROS - CV Manager", layout="wide")
init_db()

st.title("📄 Master CV Manager")
st.markdown("Manage your raw baseline CV and primary persona targets.")

# Retrieve Existing Master CV
existing_cv = get_master_cv()

st.subheader("Your Baseline (Raw) CV")

with st.form("master_cv_form"):
    title = st.text_input(
        "CV Document Title",
        value=existing_cv["title"] if existing_cv else "Master CV - Raw",
    )

    target_role = st.selectbox(
        "Primary Persona Target",
        [
            "IT Program Manager",
            "ERP Project Manager",
            "Project Controller",
            "Business Analyst",
            "PMO Manager",
            "General Master",
        ],
        index=0,
    )

    raw_text = st.text_area(
        "Raw CV Text / Content",
        value=existing_cv["raw_text"] if existing_cv else "",
        height=350,
        placeholder="Paste your raw, complete baseline CV text here...",
    )

    submitted = st.form_submit_button("💾 Save Master CV")

    if submitted:
        if not raw_text.strip():
            st.error("Please provide raw text content for your CV.")
        else:
            save_master_cv(
                title=title, raw_text=raw_text, target_role=target_role
            )
            st.success("Master CV saved successfully into AIROS SQLite DB!")
            st.rerun()

# Preview Saved Master CV
if existing_cv:
    st.divider()
    st.subheader("Current Stored Master CV")
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Title:** {existing_cv['title']}")
    with col2:
        st.info(f"**Target Role:** {existing_cv['target_role']}")

    with st.expander("Show Stored Raw Text Preview"):
        st.text(existing_cv["raw_text"])