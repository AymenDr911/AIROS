# app/utils/company.py
from datetime import datetime
from typing import Dict, Any, Optional
import streamlit as st
from utils.ids import generate_company_id

def _get_companies() -> Dict[str, Dict[str, Any]]:
    """Return the companies dictionary from session_state (lean storage)."""
    if "companies" not in st.session_state:
        st.session_state.companies = {}
    return st.session_state.companies

def find_company_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Find an existing company by name (case-insensitive)."""
    if not name:
        return None
    name_clean = name.strip().lower()
    for company in _get_companies().values():
        if company.get("name", "").strip().lower() == name_clean:
            return company
    return None

def find_or_create_company(
    name: str,
    industry: str = "",
    city: str = "",
    country: str = "",
    address: str = "",
    website: str = "",
    linkedin_url: str = "",
    phone: str = "",
    division: str = "",
) -> Dict[str, Any]:
    """
    Find an existing company by name or create a new one.
    Returns the full company dictionary.
    """
    if not name or not name.strip():
        name = "Unknown Company"

    existing = find_company_by_name(name)
    if existing:
        # Optionally enrich existing record with new data if fields were empty
        updated = False
        if not existing.get("city") and city:
            existing["city"] = city.strip()
            updated = True
        if not existing.get("country") and country:
            existing["country"] = country.strip()
            updated = True
        if not existing.get("address") and address:
            existing["address"] = address.strip()
            updated = True
        if not existing.get("website") and website:
            existing["website"] = website.strip()
            updated = True
        if not existing.get("linkedin_url") and linkedin_url:
            existing["linkedin_url"] = linkedin_url.strip()
            updated = True
        if not existing.get("phone") and phone:
            existing["phone"] = phone.strip()
            updated = True
        if not existing.get("industry") and industry:
            existing["industry"] = industry.strip()
            updated = True
        if updated:
            existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return existing

    company_id = generate_company_id()
    now = datetime.now().isoformat(timespec="seconds")

    company = {
        "company_id": company_id,
        "name": name.strip(),
        "division": division.strip() if division else "",
        "industry": industry.strip() if industry else "",
        "address": address.strip() if address else "",
        "city": city.strip() if city else "",
        "country": country.strip() if country else "",
        "website": website.strip() if website else "",
        "careers_website": "",
        "linkedin_url": linkedin_url.strip() if linkedin_url else "",
        "phone": phone.strip() if phone else "",
        "general_emails": [],
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }

    _get_companies()[company_id] = company
    return company