import streamlit as st
import json
import os
from datetime import datetime
from services.session_manager import load_users_db, save_users_db

PROFILE_KEYS = [
    "career_stage",
    "personal_identity",
    "education",
    "experience",
    "skills",
    "languages",
    "certifications",
    "cv_extracted",
    "profile_method",
    "onboarding_completed",
    "original_cv_files",          # ← must be present
]

def save_user_profile():
    """
    Save the current user's profile data into users_db.json
    under the key of the logged-in email.
    """
    user_email = st.session_state.get("user")
    if not user_email:
        return False

    users_db = load_users_db()

    if user_email not in users_db:
        users_db[user_email] = {"email": user_email}

    # Copy all profile-related keys
    profile_data = {}
    for key in PROFILE_KEYS:
        if key in st.session_state:
            profile_data[key] = st.session_state[key]

    users_db[user_email]["profile"] = profile_data
    users_db[user_email]["profile_updated_at"] = datetime.utcnow().isoformat()

    save_users_db(users_db)
    st.session_state.users_db = users_db   # keep session in sync
    return True


def load_user_profile():
    """
    Load the profile of the currently logged-in user
    from users_db.json into st.session_state.
    """
    user_email = st.session_state.get("user")
    if not user_email:
        return False

    users_db = load_users_db()
    user_data = users_db.get(user_email, {})

    profile = user_data.get("profile", {})
    if not profile:
        return False

    for key, value in profile.items():
        st.session_state[key] = value

    return True