# app/utils/contact.py
from datetime import datetime
from typing import Dict, Any, Optional, List
import streamlit as st
from utils.ids import generate_contact_id

def _get_contacts() -> Dict[str, Dict[str, Any]]:
    """Return the contacts dictionary from session_state."""
    if "contacts" not in st.session_state:
        st.session_state.contacts = {}
    return st.session_state.contacts

def create_contact(
    company_id: str,
    name: str = "",
    position: str = "",
    email: str = "",
    linkedin_url: str = "",
    contact_type: str = "General",
    source: str = "Manual",
    confidence: str = "Medium",
    verified: bool = False,
) -> Dict[str, Any]:
    """
    Create a new Contact / Recruiter record.
    Returns the full contact dictionary.
    """
    contact_id = generate_contact_id()
    now = datetime.now().isoformat(timespec="seconds")

    # Basic protection: never treat generic company emails as individual recruiters
    generic_prefixes = ("info@", "contact@", "careers@", "jobs@", "hr@", "recruitment@", "hello@")
    is_generic = any(email.lower().startswith(p) for p in generic_prefixes) if email else False

    if is_generic:
        contact_type = "General"
        confidence = "Low"

    contact = {
        "contact_id": contact_id,
        "company_id": company_id,
        "name": name.strip() if name else "",
        "position": position.strip() if position else "",
        "email": email.strip() if email else "",
        "linkedin_url": linkedin_url.strip() if linkedin_url else "",
        "contact_type": contact_type,          # HR Recruiter | Talent Acquisition | Hiring Manager | General
        "source": source,
        "confidence": confidence,              # High / Medium / Low
        "verified": verified,
        "created_at": now,
        "updated_at": now,
    }

    _get_contacts()[contact_id] = contact
    return contact

def get_contacts_by_company(company_id: str) -> List[Dict[str, Any]]:
    """Return all contacts that belong to a given company."""
    return [c for c in _get_contacts().values() if c.get("company_id") == company_id]

def get_contact(contact_id: str) -> Optional[Dict[str, Any]]:
    return _get_contacts().get(contact_id)