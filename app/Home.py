import streamlit as st

# Page configuration
st.set_page_config(
    page_title="AIROS",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sidebar Navigation Menu
with st.sidebar:
    st.title("AIROS")
    st.caption("Recruitment Operating System")
    st.divider()

    st.subheader("Menu")
    st.button("□ Jobs", use_container_width=True)
    st.button("□ ATS Analyzer", use_container_width=True)
    st.button("□ CV Manager", use_container_width=True)
    st.button("□ Applications", use_container_width=True)
    st.button("□ Analytics", use_container_width=True)

# Main Dashboard Content
st.title("Dashboard")
st.write("Welcome back.")

st.divider()

# KPI Metrics Placeholder
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Applications", value="0")

with col2:
    st.metric(label="Interviews", value="0")

with col3:
    st.metric(label="ATS Average Score", value="0%")