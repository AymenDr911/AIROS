import sys
from pathlib import Path

# Add project root directory (.../AIROS) to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from database.crud import get_dashboard_metrics, get_all_applications
from utils.nav import render_sidebar

st.set_page_config(page_title="AIROS - Analytics", page_icon="📊", layout="wide")

render_sidebar()

st.title("📊 Recruitment Pipeline Analytics")
st.markdown("High-level performance insights on application conversions and match density.")

metrics = get_dashboard_metrics()

col1, col2 = st.columns(2)
with col1:
    st.metric("Total Submitted Applications", metrics["applications"])
with col2:
    st.metric("Total Interview Calls / Screenings", metrics["interviews"])

st.divider()

apps = get_all_applications()

if not apps:
    st.info("No application data available yet. Log applications in the Applications page to view analytics.")
else:
    st.subheader("📋 Application Status Breakdown")
    status_counts = {}
    for app in apps:
        st_name = app['status']
        status_counts[st_name] = status_counts.get(st_name, 0) + 1
    
    st.bar_chart(status_counts)