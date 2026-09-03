"""AIROS V3 - backend API config (Slice 5, DEC-011).

Everything here is read from the process environment, with the same stdlib
`.env` loader used by scripts/verify_auth0.py (parity: one .env, one parser).
The Auth0 Client Secret and the Supabase service_role key are NEVER needed
here - the API is a resource server for the user's own Auth0 ID token and
keeps the RLS posture (DEC-013/DEC-014) by forwarding that token.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    """Populate os.environ from a dotenv file (existing env wins - setdefault)."""
    env_path = path or Path(".env")
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def normalize_domain(domain: str) -> str:
    """Bare host of an Auth0 domain/URL (parity: verify_auth0.normalize_domain)."""
    return (domain or "").split("//", 1)[-1].rstrip("/").lower()


class Settings:
    """Immutable-at-startup snapshot of the API configuration."""

    def __init__(self) -> None:
        load_env()
        self.env: str = os.getenv("AIROS_ENV", "dev")
        self.auth0_domain: str = normalize_domain(os.getenv("AUTH0_DOMAIN", ""))
        # The SPA sends its Auth0 ID token; its `aud` is the Auth0 application
        # (client) ID, so that is the expected audience - no extra API audience.
        self.auth0_audience: str = os.getenv("AUTH0_CLIENT_ID", "")
        self.supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.supabase_publishable_key: str = os.getenv(
            "SUPABASE_PUBLISHABLE_KEY", os.getenv("SUPABASE_ANON_KEY", "")
        )
        cors = os.getenv("AIROS_CORS_ORIGINS", "http://localhost:3000")
        self.cors_origins: list[str] = [o.strip() for o in cors.split(",") if o.strip()]
        self.api_host: str = os.getenv("API_HOST", "127.0.0.1")
        self.api_port: int = int(os.getenv("API_PORT", "8001"))

    @property
    def issuer(self) -> str:
        return f"https://{self.auth0_domain}/"

    @property
    def jwks_url(self) -> str:
        return f"https://{self.auth0_domain}/.well-known/jwks.json"

    def missing_critical(self) -> list[str]:
        """Names of config values the API cannot verify tokens without."""
        missing: list[str] = []
        if not self.auth0_domain:
            missing.append("AUTH0_DOMAIN")
        if not self.auth0_audience:
            missing.append("AUTH0_CLIENT_ID")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
