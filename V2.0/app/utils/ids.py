# app/utils/ids.py
from datetime import datetime
import streamlit as st

def _get_next_counter(entity: str) -> int:
    """Simple auto-increment counter stored in session_state (lean)."""
    key = f"_id_counter_{entity}"
    if key not in st.session_state:
        st.session_state[key] = 0
    st.session_state[key] += 1
    return st.session_state[key]

def generate_job_id() -> str:
    year = datetime.now().year
    seq = _get_next_counter("job")
    return f"JOB-{year}-{seq:06d}"

def generate_company_id() -> str:
    year = datetime.now().year
    seq = _get_next_counter("company")
    return f"COMP-{year}-{seq:06d}"

def generate_contact_id() -> str:
    year = datetime.now().year
    seq = _get_next_counter("contact")
    return f"CONT-{year}-{seq:06d}"