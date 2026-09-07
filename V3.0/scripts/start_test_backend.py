"""Start a test backend server with monkeypatched JWKS + real Gemini API.

Accepts test tokens (signed with a test RSA key) while using the real
GEMINI_API_KEY from .env. Useful for end-to-end curl / puppeteer tests.
"""
import os
import sys
import threading

# Load .env first (for GEMINI_API_KEY)
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

# Set test auth env (MUST override .env values)
os.environ["AUTH0_DOMAIN"] = "test-tenant.eu.auth0.com"
os.environ["AUTH0_CLIENT_ID"] = "test-client-id"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_PUBLISHABLE_KEY"] = "test-publishable-key"
os.environ["AIROS_CORS_ORIGINS"] = "http://localhost:3000"
os.environ["AIROS_ENV"] = "test"
os.environ["API_HOST"] = "127.0.0.1"
os.environ["API_PORT"] = "8002"

# Monkeypatch JWKS
import services.api.auth as auth_mod
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import base64
import time

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
pub = key.public_key().public_numbers()

def _b64url_int(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

jwks = {
    "keys": [{
        "kty": "RSA", "kid": "test-key", "use": "sig", "alg": "RS256",
        "n": _b64url_int(pub.n), "e": _b64url_int(pub.e),
    }]
}
auth_mod.get_jwks = lambda force=False: jwks

# Clear settings cache so test env takes effect
import services.api.config as config_mod
config_mod.get_settings.cache_clear()

# Also write the test private key to a file for token minting
keyfile = Path("/tmp/test_rsa_key.pem")
keyfile.write_text(private_pem.decode("utf-8"))
print(f"Test RSA key written to {keyfile}")
print(f"GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))}")
print("Starting test backend on port 8002...")

import uvicorn
from services.api.main import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
