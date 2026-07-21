import streamlit as st

def render_sidebar():
    with st.sidebar:
        st.markdown("## 🚀 **AIROS**")
        st.caption("Recruitment Operating System")
        st.divider()

        # Custom navigation links
        st.page_link("Home.py", label="Dashboard", icon="🏠")
        st.page_link("pages/1_CV_Manager.py", label="CV Manager", icon="📄")
        st.page_link("pages/2_Jobs.py", label="Jobs", icon="💼")
        st.page_link("pages/3_ATS_Analyzer.py", label="ATS Analyzer", icon="🎯")
        st.page_link("pages/4_Applications.py", label="Applications", icon="📋")
        st.page_link("pages/5_Analytics.py", label="Analytics", icon="📊")