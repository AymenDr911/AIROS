"""AIROS V3 - backend config tests (Slice 5): env parsing + derived URLs."""

from __future__ import annotations

import pytest

from tests.conftest import CLIENT_ID, DOMAIN


def test_settings_from_env(api_env):
    from services.api.config import get_settings

    s = get_settings()
    assert s.auth0_domain == DOMAIN
    assert s.auth0_audience == CLIENT_ID
    assert s.issuer == f"https://{DOMAIN}/"
    assert s.jwks_url == f"https://{DOMAIN}/.well-known/jwks.json"
    assert s.cors_origins == ["http://localhost:3000"]
    assert s.api_port == 8001
    assert s.missing_critical() == []


def test_normalize_domain_accepts_url_form():
    from services.api.config import normalize_domain

    assert normalize_domain("https://TENANT.eu.auth0.com/") == "tenant.eu.auth0.com"
    assert normalize_domain("tenant.eu.auth0.com") == "tenant.eu.auth0.com"
    assert normalize_domain("") == ""


def test_cors_multiple_origins(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", DOMAIN)
    monkeypatch.setenv("AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AIROS_CORS_ORIGINS", "http://localhost:3000, https://airos.example.app")
    from services.api.config import get_settings

    get_settings.cache_clear()
    try:
        assert get_settings().cors_origins == [
            "http://localhost:3000",
            "https://airos.example.app",
        ]
    finally:
        get_settings.cache_clear()


def test_missing_critical_config_detected(monkeypatch):
    monkeypatch.setattr("services.api.config.load_env", lambda path=None: None)
    from services.api.config import Settings

    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_CLIENT_ID", raising=False)
    s = Settings()
    assert "AUTH0_DOMAIN" in s.missing_critical()
    assert "AUTH0_CLIENT_ID" in s.missing_critical()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0001", 1), ("8080", 8080)],
)
def test_api_port_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("API_PORT", value)
    from services.api.config import Settings

    assert Settings().api_port == expected
