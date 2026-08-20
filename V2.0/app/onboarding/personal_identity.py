import streamlit as st


def render_personal_identity():
    st.title("Personal Identity")
    st.markdown("Tell us a bit about yourself. You can always edit this later.")
    st.markdown("---")

    # Progress indicator
    st.caption("Step 2 of 9 — Personal Identity")
    st.progress(20)

    # -------------------------------------------------
    # Pre-fill from AI extraction if available
    # -------------------------------------------------
    ai_data = {}
    if st.session_state.get("profile_method") == "ai" and st.session_state.get("cv_extracted"):
        ai_data = st.session_state.cv_extracted.get("personal_identity", {})
        st.info("Fields pre-filled from your CV. Please review and adjust if needed.")

    def get_value(ai_key, session_key, default=""):
        if ai_data.get(ai_key):
            return ai_data.get(ai_key)
        return st.session_state.get(session_key, default)

    # Split full name
    full_name = get_value("full_name", "full_name", "")
    first_name_default = st.session_state.get("first_name", "")
    last_name_default = st.session_state.get("last_name", "")

    if full_name and not first_name_default and not last_name_default:
        parts = full_name.strip().split()
        if len(parts) >= 2:
            first_name_default = parts[0]
            last_name_default = " ".join(parts[1:])
        else:
            first_name_default = full_name

    # Location
    location = get_value("location", "location", "")
    country_default = st.session_state.get("country", "")
    city_default = st.session_state.get("city", "")

    if location and not country_default:
        if "," in location:
            city_default = location.split(",")[0].strip()
            country_default = location.split(",")[-1].strip()
        else:
            country_default = location

    # -------------------------------------------------
    # Form
    # -------------------------------------------------
    col1, col2 = st.columns(2)

    with col1:
        first_name = st.text_input("First Name *", value=first_name_default)
        country = st.text_input("Country *", value=country_default)
        nationality = st.text_input(
            "Nationality *",
            value=st.session_state.get("nationality", country_default)
        )

    with col2:
        last_name = st.text_input("Last Name *", value=last_name_default)
        city = st.text_input("City (optional)", value=city_default)

        # Smart Visa Sponsorship logic
        eu_countries = [
            "france", "germany", "belgium", "netherlands", "luxembourg", "italy", "spain",
            "portugal", "austria", "ireland", "finland", "greece", "slovakia", "slovenia",
            "estonia", "latvia", "lithuania", "cyprus", "malta", "croatia", "sweden", "denmark",
            "poland", "czech republic", "czechia", "hungary", "romania", "bulgaria"
        ]

        is_non_eu = nationality and nationality.strip().lower() not in eu_countries
        requires_visa = False
        visa_status = st.session_state.get("visa_status", "")

        if is_non_eu:
            st.warning("Your nationality is outside the EU/EEA.")
            requires_visa = st.checkbox(
                "I require visa sponsorship",
                value=True,
                key="requires_visa_checkbox"
            )

            if requires_visa:
                visa_status = st.radio(
                    "Please clarify your situation:",
                    options=[
                        "I need Employer sponsorship",
                        "I already hold a special visa / residence permit"
                    ],
                    index=0 if st.session_state.get("visa_status") != "I already hold a special visa / residence permit" else 1,
                    key="visa_status_radio"
                )
            else:
                visa_status = "No sponsorship required"
        else:
            requires_visa = False
            visa_status = "EU/EEA citizen"

    st.markdown("### Additional Information")
    col3, col4 = st.columns(2)

    with col3:
        has_license = st.checkbox(
            "I have a driver’s license",
            value=st.session_state.get("has_driver_license", False)
        )
        whatsapp = st.text_input(
            "WhatsApp number (for interviews)",
            value=st.session_state.get("whatsapp", get_value("phone", "phone", "")),
            placeholder="+216 XX XXX XXX"
        )

    with col4:
        linkedin = st.text_input(
            "LinkedIn URL (optional)",
            value=get_value("linkedin", "linkedin_url", "")
        )
        github = st.text_input(
            "GitHub URL (optional)",
            value=get_value("github", "github_url", "")
        )

    st.markdown("### Languages")
    languages_default = st.session_state.get("languages_text", "")
    if not languages_default and st.session_state.get("cv_extracted"):
        ai_langs = st.session_state.cv_extracted.get("languages", [])
        if ai_langs:
            languages_default = ", ".join(
                [f"{l.get('language', '')} {l.get('level', '')}".strip() for l in ai_langs]
            )

    languages = st.text_input(
        "Languages you speak (e.g. French C2, English C1, Arabic Native)",
        value=languages_default
    )

    st.markdown("---")

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])

    with col_btn1:
        if st.button("← Back"):
            st.session_state.onboarding_step = "career_stage"
            st.rerun()

    with col_btn2:
        save_btn = st.button("Save & Continue →", type="primary", use_container_width=True)

    if save_btn:
        if not first_name or not last_name or not country or not nationality:
            st.error("Please fill all required fields (*)")
            return

        # Save everything
        st.session_state.first_name = first_name.strip()
        st.session_state.last_name = last_name.strip()
        st.session_state.country = country.strip()
        st.session_state.city = city.strip()
        st.session_state.nationality = nationality.strip()
        st.session_state.requires_visa_sponsorship = requires_visa
        st.session_state.visa_status = visa_status
        st.session_state.has_driver_license = has_license
        st.session_state.whatsapp = whatsapp.strip()
        st.session_state.linkedin_url = linkedin.strip()
        st.session_state.github_url = github.strip()
        st.session_state.languages_text = languages.strip()

        st.session_state.personal_identity = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "country": country.strip(),
            "city": city.strip(),
            "nationality": nationality.strip(),
            "linkedin": linkedin.strip(),
            "github": github.strip(),
            "whatsapp": whatsapp.strip(),
            "languages": languages.strip(),
            "requires_visa_sponsorship": requires_visa,
            "visa_status": visa_status,
        }
        from services.profile_service import save_user_profile
        save_user_profile()

        st.session_state.onboarding_step = "education"
        st.success("Personal information saved!")
        st.rerun()