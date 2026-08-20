import streamlit as st
import json
import os
from datetime import datetime

USERS_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "users_db.json")

def _ensure_data_folder():
    os.makedirs(os.path.dirname(USERS_DB_PATH), exist_ok=True)

def load_users_db() -> dict:
    _ensure_data_folder()
    if os.path.exists(USERS_DB_PATH):
        try:
            with open(USERS_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users_db(users_db: dict):
    _ensure_data_folder()
    with open(USERS_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(users_db, f, indent=2, ensure_ascii=False)

def initialize_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "auth_method" not in st.session_state:
        st.session_state.auth_method = None

    # Always load the persistent users database
    if "users_db" not in st.session_state:
        st.session_state.users_db = load_users_db()

    # Pre-create a permanent test account if it does not exist
    test_email = "test@airos.demo"
    if test_email not in st.session_state.users_db:
        st.session_state.users_db[test_email] = {
            "email": test_email,
            "password": "Test1234!",
            "status": "ACTIVE",
            "created_at": datetime.utcnow().isoformat(),
            "verification_token": "AIROS-TEST",
        }
        save_users_db(st.session_state.users_db)

def login_user(user, method="Email"):
    st.session_state.logged_in = True
    st.session_state.user = user
    st.session_state.auth_method = method

    # ──────────────────────────────────────────────
    # NEW: Restore the full profile from JSON
    # ──────────────────────────────────────────────
    from services.profile_service import load_user_profile
    load_user_profile()

def logout():
    # Soft logout – only clear authentication, keep profile data for testing
    for key in ["logged_in", "user", "auth_method"]:
        if key in st.session_state:
            del st.session_state[key]

def require_auth():
    initialize_session()
    if not st.session_state.logged_in:
        st.warning("Please log in to access this resource.")
        st.stop()