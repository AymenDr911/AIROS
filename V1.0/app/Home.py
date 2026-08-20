import sys
from pathlib import Path

# Add project root directory (.../AIROS) to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from database.crud import get_dashboard_metrics
from utils.nav import render_sidebar

# Ensure SQLite database tables are created on startup (fixes Streamlit Cloud missing table error)
try:
    from database.db import init_db
    init_db()
except Exception:
    pass

# Configure page layout without icons
st.set_page_config(page_title="AIROS - Dashboard", layout="wide")

render_sidebar()

st.title("Dashboard")
st.markdown("Welcome back to **AIROS**.")

st.divider()

# Fetch live metrics safely
metrics = get_dashboard_metrics()

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Total Applications", value=metrics.get("applications", 0))

with col2:
    st.metric(label="Interviews / Screenings", value=metrics.get("interviews", 0))

with col3:
    st.metric(
        label="Avg ATS Match Score",
        value=f"{metrics.get('avg_ats_score', 0)}%",
    )

st.divider()

st.subheader("Quick Actions")
q1, q2, q3 = st.columns(3)

if q1.button("Manage Baseline CV"):
    st.switch_page("pages/1_CV_Manager.py")

if q2.button("Add New Job Offer"):
    st.switch_page("pages/2_Jobs.py")

if q3.button("Run ATS Analysis"):
    st.switch_page("pages/3_ATS_Analyzer.py")