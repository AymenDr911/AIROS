import streamlit as st

def render_footer():
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #64748B; font-size: 14px;'>
            <p><strong>AIROS V2</strong> | Enterprise ERP Program Management Suite v2.0.1<br>
            Support & Contact: <a href='mailto:support@airos.internal' style='color: #2563EB;'>support@airos.internal</a></p>
        </div>
        """,
        unsafe_allow_html=True
    )