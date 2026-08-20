import streamlit as st
import re
from datetime import datetime
from typing import Tuple, List
from services.session_manager import login_user, initialize_session, save_users_db
from components.footer import render_footer

def is_strong_password(password: str) -> Tuple[bool, List[str]]:
    """Returns (is_valid, list of failed rules)"""
    errors = []
    if len(password) < 8:
        errors.append("At least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("One uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("One lowercase letter")
    if not re.search(r"\d", password):
        errors.append("One number")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        errors.append("One special character")
    return len(errors) == 0, errors


def render_auth():
    initialize_session()  # this now loads the persistent users_db + creates test account

    st.markdown(
        "<h1 style='text-align: center; margin-bottom: 0.2rem;'>🚀 AIROS V2</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; color: #94a3b8; margin-top: 0;'>Secure Access & Executive Command Center</p>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2.2, 1])
    with col2:
        # ── Primary Social Options (Google + Apple) ─────
        st.markdown("### Continue with")
        s1, s2 = st.columns(2)
        with s1:
            if st.button("🔵 Continue with Google", use_container_width=True, key="sso_google", type="secondary"):
                login_user("google.user@airos.demo", method="Google OAuth")
                st.rerun()

        with s2:
            if st.button(" Continue with Apple", use_container_width=True, key="sso_apple", type="secondary"):
                login_user("apple.user@airos.demo", method="Apple ID")
                st.rerun()

        st.markdown(
            "<p style='text-align: center; color: #64748B; margin: 1rem 0;'>— or continue with email —</p>",
            unsafe_allow_html=True,
        )

        tab_signin, tab_register, tab_verify = st.tabs(
            ["Sign In", "Create Account", "Verify Email"]
        )

        # ══════════════════════════════════════
        # SIGN IN
        # ══════════════════════════════════════
        with tab_signin:
            st.subheader("Welcome back")
            email = st.text_input("Work Email", key="login_email", placeholder="name@company.com")
            password = st.text_input("Password", type="password", key="login_pass")

            if st.button("Sign In", type="primary", use_container_width=True, key="btn_login"):
                email = email.strip().lower()
                user = st.session_state.users_db.get(email)

                if not email or not password:
                    st.error("Please enter email and password.")
                elif not user:
                    st.error("No account found with this email.")
                elif user["status"] != "ACTIVE":
                    st.warning("Account not yet verified. Please check the Verify Email tab.")
                elif user["password"] != password:
                    st.error("Incorrect password.")
                else:
                    login_user(email, method="Email + Password")
                    st.success("Authentication successful")
                    st.rerun()

        # ══════════════════════════════════════
        # REGISTER
        # ══════════════════════════════════════
        with tab_register:
            st.subheader("Create your AIROS account")
            new_email = st.text_input("Work Email", key="reg_email", placeholder="name@company.com")
            new_pass = st.text_input("Password", type="password", key="reg_pass")
            confirm_pass = st.text_input("Confirm Password", type="password", key="reg_confirm")

            # Live password strength
            if new_pass:
                is_valid, errors = is_strong_password(new_pass)
                if is_valid:
                    st.success("Password meets security policy")
                else:
                    st.warning("Password requirements not met:")
                    for e in errors:
                        st.caption(f"• {e}")

            terms = st.checkbox("I accept the Terms of Service")
            privacy = st.checkbox("I accept the Privacy Policy (GDPR)")

            if st.button("Create Account", type="primary", use_container_width=True, key="btn_register"):
                email = new_email.strip().lower()
                if not email or not new_pass:
                    st.error("Email and password are required.")
                elif new_pass != confirm_pass:
                    st.error("Passwords do not match.")
                elif not is_strong_password(new_pass)[0]:
                    st.error("Password does not meet the security policy (8+ chars, upper, lower, number, symbol).")
                elif not terms or not privacy:
                    st.error("You must accept Terms of Service and Privacy Policy.")
                elif email in st.session_state.users_db:
                    st.error("An account with this email already exists.")
                else:
                    token = "AIROS-" + email[:8].upper().replace(".", "").replace("@", "")
                    st.session_state.users_db[email] = {
                        "email": email,
                        "password": new_pass,  # DEMO ONLY
                        "status": "PENDING_EMAIL_VERIFICATION",
                        "created_at": datetime.utcnow().isoformat(),
                        "verification_token": token,
                    }
                    save_users_db(st.session_state.users_db)
                    st.success("Account created successfully!")
                    st.info(
                        f"**Next step:** Go to the **Verify Email** tab and enter this token:\n\n"
                        f"### `{token}`\n\n"
                        f"(In production a real email would be sent to **{email}**)"
                    )

        # ══════════════════════════════════════
        # VERIFY EMAIL
        # ══════════════════════════════════════
        with tab_verify:
            st.subheader("Email Verification")
            st.write("In production this step happens when the user clicks the link in their inbox.")
            st.write("For this demo, enter the token that was shown after registration.")

            ver_email = st.text_input("Email used for registration", key="ver_email")
            ver_token = st.text_input("Verification Token", key="ver_token")

            if st.button("Activate Account", type="primary", use_container_width=True, key="btn_verify"):
                email = ver_email.strip().lower()
                user = st.session_state.users_db.get(email)

                if not user:
                    st.error("No pending account found for this email.")
                elif user["status"] == "ACTIVE":
                    st.info("This account is already active. You can Sign In.")
                elif user["verification_token"] != ver_token.strip():
                    st.error("Invalid verification token.")
                else:
                    user["status"] = "ACTIVE"
                    save_users_db(st.session_state.users_db)
                    st.success("Email verified successfully! Your account is now active.")
                    st.balloons()
                    st.info("You can now go to the Sign In tab.")

    render_footer()