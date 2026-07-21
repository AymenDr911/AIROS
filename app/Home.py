import os
import sys
import streamlit as st

# Add project root directory to Python path
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from database.crud import get_dashboard_metrics
from database.db import init_db

# Initialize page config & database
st.set_page_config(page_title="AIROS - Dashboard", layout="wide")
init_db()

# Custom Sidebar Navigation
st.sidebar.title("AIROS")
st.sidebar.caption("Recruitment Operating System")
st.sidebar.markdown("---")

st.sidebar.subheader("Menu")

# Navigation buttons using st.switch_page
if st.sidebar.button("💼 Jobs", use_container_width=True):
    st.info("Jobs page coming up next!")

if st.sidebar.button("🎯 ATS Analyzer", use_container_width=True):
    st.info("ATS Analyzer page coming soon!")

if st.sidebar.button("📄 CV Manager", use_container_width=True):
    st.switch_page("pages/1_CV_Manager.py")

if st.sidebar.button("📋 Applications", use_container_width=True):
    st.info("Applications page coming soon!")

if st.sidebar.button("📊 Analytics", use_container_width=True):
    st.info("Analytics page coming soon!")

# Main Dashboard Content
st.title("Dashboard")
st.write("Welcome back.")

st.divider()

# Fetch live metrics from DB
metrics = get_dashboard_metrics()

col1, col2, col3 = st.columns(3)
col1.metric("Applications", metrics["applications"])
col2.metric("Interviews", metrics["interviews"])
col3.metric("ATS Average Score", f"{metrics['avg_ats']}%")