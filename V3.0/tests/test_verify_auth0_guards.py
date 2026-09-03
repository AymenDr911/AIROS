"""AIROS V3 — verify_auth0.py token-guard unit tests (Slice 3)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_auth0.py"

spec = importlib.util.spec_from_file_location("verify_auth0", SCRIPT)
assert spec and spec.loader
verify_auth0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_auth0)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# normalize_domain
# ---------------------------------------------------------------------------

def test_normalize_domain_strips_scheme_and_slash():
    assert verify_auth0.normalize_domain("https://dev-x.eu.auth0.com/") == "dev-x.eu.auth0.com"
    assert verify_auth0.normalize_domain("dev-x.eu.auth0.com") == "dev-x.eu.auth0.com"
    assert verify_auth0.normalize_domain("") == ""
    assert verify_auth0.normalize_domain("HTTPS://DEV-X.EU.AUTH0.COM") == "dev-x.eu.auth0.com"


# ---------------------------------------------------------------------------
# token_role_error
# ---------------------------------------------------------------------------

def test_role_error_when_not_authenticated():
    msg = verify_auth0.token_role_error({"role": ""})
    assert msg is not None and "is not 'authenticated'" in msg
    assert verify_auth0.token_role_error({"role": "anon"}) is not None
    assert verify_auth0.token_role_error({"role": None}) is not None  # missing claim


def test_role_ok_when_authenticated():
    assert verify_auth0.token_role_error({"role": "authenticated"}) is None


# ---------------------------------------------------------------------------
# token_iss_warning
# ---------------------------------------------------------------------------

DOMAIN = "dev-s6kc2wm7ppaoj8ni.eu.auth0.com"


def test_iss_exact_match_no_warning_with_or_without_scheme():
    # Auth0 `iss` has scheme + trailing slash; this must NOT warn.
    assert verify_auth0.token_iss_warning(f"https://{DOMAIN}/", DOMAIN) is None
    assert verify_auth0.token_iss_warning(DOMAIN, DOMAIN) is None
    assert verify_auth0.token_iss_warning("", DOMAIN) is None  # no token claim


def test_iss_mismatch_warns():
    msg = verify_auth0.token_iss_warning("https://other.eu.auth0.com/", DOMAIN)
    assert msg is not None and "does not match AUTH0_DOMAIN" in msg


# ---------------------------------------------------------------------------
# token_aud_warning
# ---------------------------------------------------------------------------

CLIENT_ID = "mIqi9un7HPVTP8Ej5xlmXkkosUXYArDJ"


def test_aud_exact_match_no_warning():
    assert verify_auth0.token_aud_warning(CLIENT_ID, CLIENT_ID) is None


def test_aud_mismatch_warns():
    msg = verify_auth0.token_aud_warning("wrong-app", CLIENT_ID)
    assert msg is not None and "does not match AUTH0_CLIENT_ID" in msg


def test_aud_missing_does_not_warn():
    assert verify_auth0.token_aud_warning(None, CLIENT_ID) is None
    assert verify_auth0.token_aud_warning("", CLIENT_ID) is None