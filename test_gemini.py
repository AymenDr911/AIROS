import json
import os
import urllib.error
import urllib.request

# 1. Locate API key from .streamlit/secrets.toml
api_key = None
secrets_path = os.path.join(".streamlit", "secrets.toml")

if os.path.exists(secrets_path):
  with open(secrets_path, "r") as f:
    for line in f:
      if "GEMINI_API_KEY" in line and "=" in line:
        api_key = line.split("=", 1)[1].strip().strip("\"'")
        break

if not api_key:
  api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
  print("❌ ERROR: Could not find GEMINI_API_KEY in .streamlit/secrets.toml")
  exit(1)

# Active Gemini Flash model
MODEL = "gemini-3.5-flash"
print(f"🔑 Found API Key: {api_key[:8]}... (Testing connection to {MODEL})\n")

url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

payload = {
    "contents": [{"parts": [{"text": "Say 'API Connection Successful!'"}]}]
}

req = urllib.request.Request(
    url, data=json.dumps(payload).encode("utf-8"), headers=headers
)

try:
  with urllib.request.urlopen(req, timeout=30) as response:
    result = json.loads(response.read().decode("utf-8"))
    answer = result["candidates"][0]["content"]["parts"][0]["text"]
    print("✅ SUCCESS!")
    print(f"Gemini Response: {answer.strip()}")
except urllib.error.HTTPError as e:
  error_body = e.read().decode("utf-8", errors="ignore")
  print(f"❌ HTTP ERROR {e.code}: {e.reason}")
  print(f"Details: {error_body}")
except Exception as e:
  print(f"❌ CONNECTION ERROR: {str(e)}")