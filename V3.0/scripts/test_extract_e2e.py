"""End-to-end test of the extraction endpoint with the REAL Gemini API.

Uses the same RSA keypair approach as tests/conftest.py but does NOT mock
extract_rich_profile_from_text, so the real Gemini call runs.
"""
import sys
import io
import json
import time
import tempfile
import os

# Set test env BEFORE importing the app
os.environ["AIROS_ENV"] = "test"
os.environ["AUTH0_DOMAIN"] = "test-tenant.eu.auth0.com"
os.environ["AUTH0_CLIENT_ID"] = "test-client-id"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_PUBLISHABLE_KEY"] = "test-publishable-key"
os.environ["AIROS_CORS_ORIGINS"] = "http://localhost:3000"
os.environ["API_HOST"] = "127.0.0.1"
os.environ["API_PORT"] = "8001"

# Load the .env for GEMINI_API_KEY but allow test overrides to win
import services.api.config as config_mod
config_mod.load_env()  # loads .env -> GEMINI_API_KEY etc.
config_mod.get_settings.cache_clear()

# Monkeypatch JWKS to use test key
import services.api.auth as auth_mod
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
pub = key.public_key().public_numbers()
import base64
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

# Mint a token
import jwt, time as time_mod
now = int(time_mod.time())
claims = {
    "iss": "https://test-tenant.eu.auth0.com/",
    "aud": "test-client-id",
    "sub": "auth0|testuser",
    "email": "tester@airos.dev",
    "role": "authenticated",
    "iat": now,
    "exp": now + 600,
}
token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "test-key"})

# Create app and TestClient
from fastapi.testclient import TestClient
from services.api.main import create_app

app = create_app()
client = TestClient(app)

# Build a simple DOCX file
from docx import Document
doc = Document()
doc.add_paragraph("John Doe Senior Engineer with 8 years of experience in Python, SQL, Docker, Kubernetes, AWS, Agile, Scrum. Led a team of 5 engineers. Managed PostgreSQL databases. Built CI/CD pipelines.")
buf = io.BytesIO()
doc.save(buf)
docx_bytes = buf.getvalue()

print("Sending extraction request with REAL Gemini API...")
start = time.time()
resp = client.post(
    "/api/profile/extract-cv",
    headers={"Authorization": f"Bearer {token}"},
    files=[("files", ("cv.docx", docx_bytes, "application/octet-stream"))],
    timeout=120,
)
elapsed = time.time() - start
print(f"Response: HTTP {resp.status_code} in {elapsed:.1f}s")
print(f"Body: {json.dumps(resp.json(), indent=2)[:2000]}")
