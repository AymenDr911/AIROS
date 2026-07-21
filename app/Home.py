import os
import sys
import streamlit as st

# Add project root directory to Python search path
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from database.crud import get_dashboard_metrics
from database.db import init_db
from utils.nav import render_sidebar

# Page Configuration
st.set_page_config(page_title="AIROS - Dashboard", layout="wide")
init_db()
render_sidebar()

st.title("🏠 Dashboard")
st.markdown("Welcome back to **AIROS**.")

st.divider()

# --- METRICS DISPLAY ---
metrics = get_dashboard_metrics()

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Applications", value=metrics.get("applications_count", 0))

with col2:
    st.metric(label="Interviews", value=metrics.get("interviews_count", 0))

with col3:
    st.metric(
        label="ATS Average Score",
        value=f"{metrics.get('avg_ats_score', 0.0):.1f}%",
    )