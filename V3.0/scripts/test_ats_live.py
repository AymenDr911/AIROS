"""Raw Gemini API diagnostic - bypasses the gateway entirely.

1. Lists available models for the configured key.
2. Sends the exact ATS parse prompt with json_mode and prints the RAW response.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # type: ignore

load_dotenv(os.path.join(ROOT, ".env"))

API_KEY = os.getenv("GEMINI_API_KEY", "")
BASE = "https://generativelanguage.googleapis.com/v1beta"

# ---------------------------------------------------------------- models list
req = urllib.request.Request(
    f"{BASE}/models?key={API_KEY}&pageSize=100",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    models = [
        m["name"].split("/")[-1]
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    print(f"AVAILABLE generateContent models ({len(models)}):")
    for m in models:
        print("  -", m)
except Exception as exc:  # noqa: BLE001
    print(f"MODELS LIST FAILED: {exc}")

# ------------------------------------------------------------- raw completion
JD = """Registered Nurse - ICU
Requirements: BSN, valid RN license, 2+ years ICU experience, BLS and ACLS
certifications. Salary $75,000-$95,000."""

PROMPT = f"""You are a senior recruitment analyst specialized in precise, non-hallucinated job parsing.
Extract a structured job profile from the Job Description below.
Return ONLY valid JSON that strictly follows the schema. Never invent requirements that are not clearly present.

Schema:
{{
  "job_title": "", "company_name": "", "location": "", "country": "", "city": "",
  "industry": "", "seniority_level": "",
  "required_skills": {{"technical": [], "methodologies": [], "tools": []}},
  "experience": {{"min_years": 0, "preferred_years": 0, "level": ""}},
  "education": {{"min_degree": "", "preferred_fields": []}},
  "languages": [{{"language": "", "level": "", "required": false}}],
  "certifications": []
}}

If the information is not present, leave the field as empty string "".

Job Description:
{JD}
"""

for model in ["gemini-2.5-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]:
    print("=" * 70)
    print(f"MODEL: {model}")
    payload = {
        "contents": [{"parts": [{"text": PROMPT}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    url = f"{BASE}/models/{model}:generateContent?key={API_KEY}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            result = json.loads(r.read().decode())
        cand = result.get("candidates", [])
        if not cand:
            print(f"  NO CANDIDATES. raw: {json.dumps(result)[:500]}")
            continue
        finish = cand[0].get("finishReason")
        parts = cand[0].get("content", {}).get("parts", [])
        text = parts[0].get("text", "") if parts else ""
        print(f"  finishReason: {finish}")
        print(f"  text ({len(text)} chars): {text[:600]}")
        if not text:
            print(f"  full candidate: {json.dumps(cand[0])[:500]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:400]
        print(f"  HTTP {e.code}: {body}")
    except Exception as exc:  # noqa: BLE001
        print(f"  EXC: {exc}")

