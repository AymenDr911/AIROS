"""AIROS V3 - Profile creation flow tests (Slice 6, CHG-014).

Covers the V2-parity endpoints offline:
- POST /api/profile/extract-cv: auth guard, file-type guard, real DOCX/PDF
  text extraction, Gemini mocked at the router boundary, originals saved to
  a tmp uploads dir (metadata-only, ISS-006).
- PUT /api/profile: runs the EXACT migration transform_profile (identity
  mapping, skills reclassification, evidence rule, V2 onboarding metadata)
  and upserts via PostgREST with the caller's token (mocked transport).
"""

from __future__ import annotations

import httpx
import io
import json

from tests.conftest import mint_token

V2_PAYLOAD = {
    "career_stage": "Experienced Professional (3–8 years)",
    "personal_identity": {
        "first_name": "Aymen",
        "last_name": "Dr",
        "country": "France",
        "city": "Paris",
        "nationality": "Tunisian",
        "linkedin": "https://linkedin.com/in/x",
        "github": "",
        "whatsapp": "+216 20 000 000",
        "languages": "French C2, English C1, Arabic Native",
        "requires_visa_sponsorship": True,
        "visa_status": "Requires sponsorship",
        "has_driver_license": True,
    },
    "education": [
        {"degree": "Master", "institution": "UT", "field_of_study": "IS",
         "status": "Completed", "start_year": "2019", "end_year": "2023"}
    ],
    "experience": [
        {"company": "Acme", "title": "Engineer", "location": "Paris",
         "employment_type": "Full-time", "start_date": "01.2016",
         "end_date": "", "currently_working": True, "description": "Built things"}
    ],
    "skills": {"technical": ["Python", "SQL"], "methodologies": ["Scrum"],
               "tools": ["Odoo"], "core": ["Communication"]},
    "languages": [{"language": "French", "level": "C2"}],
    "certifications": [{"name": "PMP", "issuer": "PMI", "year": "2020"}],
    "profile_method": "ai",
    "onboarding_completed": True,
    "saved_files": [{"original_name": "cv.pdf", "saved_as": "original_cv_1.pdf",
                     "storage_ref": "local://data/uploads/x/original_cv_1.pdf",
                     "uploaded_at": "2026-09-03T00:00:00+00:00", "size_kb": 12.3}],
}


def test_extract_cv_requires_auth(client):
    resp = client.post("/api/profile/extract-cv")
    assert resp.status_code == 401


def test_extract_cv_rejects_unsupported_type(client, rsa_material):
    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/profile/extract-cv",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 400
    assert "PDF or DOCX" in resp.json()["detail"]


def _make_docx_bytes(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(text: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(page.rect, text)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf.getvalue()


RICH_DATA = {
    "personal_identity": {"full_name": "Aymen Dr", "email": "a@b.c", "location": "Paris, France"},
    "career_stage_suggestion": "Experienced Professional (3–8 years)",
    "education": [{"degree": "Master", "field": "IS", "institution": "UT", "start_year": "2019"}],
    "professional_experience": [{"company": "Acme", "role": "Engineer", "start_date": "03.2020", "currently_working": True, "achievements": ["did x"]}],
    "skills": {"technical": ["Python"], "methodologies": ["Agile"], "tools": [], "core": ["Teamwork"]},
    "languages": [{"language": "French", "level": "C2"}],
    "certifications": [],
}


def _stub_gateway(monkeypatch, rich_data: dict) -> None:
    import services.api.routers.profile as profile_router

    monkeypatch.setattr(profile_router, "extract_rich_profile_from_text", lambda text, key: json.loads(json.dumps(rich_data)))


def test_extract_cv_docx_full_path(client, rsa_material, monkeypatch, tmp_path):
    import os

    monkeypatch.chdir(tmp_path)  # uploads land in tmp (V2 dir shape, no repo pollution)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _stub_gateway(monkeypatch, RICH_DATA)

    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/profile/extract-cv",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("my_cv.docx", _make_docx_bytes("John Doe Senior Engineer " * 10), "application/octet-stream"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rich_data"]["personal_identity"]["full_name"] == "Aymen Dr"
    assert body["career_stage_suggestion"] == "Experienced Professional (3–8 years)"
    assert body["strong_evidence"] is True  # currently_working counts (migration rule)
    assert len(body["saved_files"]) == 1
    saved = body["saved_files"][0]
    assert saved["original_name"] == "my_cv.docx"
    assert saved["saved_as"] == "original_cv_1.docx"
    assert saved["storage_ref"].startswith("local://")
    assert saved["size_kb"] > 0
    assert os.path.exists(saved["path"])  # original bytes on disk (V2 parity)
    with open(saved["path"], "rb") as fh:
        assert fh.read(2) == b"PK"  # real DOCX content stored (zip magic)


def test_extract_cv_pdf_full_path(client, rsa_material, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _stub_gateway(monkeypatch, RICH_DATA)

    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/profile/extract-cv",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("cv.pdf", _make_pdf_bytes("John Doe Senior QA Lead " * 10), "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["saved_files"][0]["saved_as"] == "original_cv_1.pdf"


def test_extract_cv_gateway_failure_maps_to_502(client, rsa_material, monkeypatch, tmp_path):
    from ai.gateway import GatewayError

    import services.api.routers.profile as profile_router

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(text, key):
        raise GatewayError("Gemini API Connection Failed.")

    monkeypatch.setattr(profile_router, "extract_rich_profile_from_text", boom)

    token = mint_token(rsa_material[0])
    resp = client.post(
        "/api/profile/extract-cv",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("cv.docx", _make_docx_bytes("Some text " * 50), "application/octet-stream"))],
    )
    assert resp.status_code == 502
    assert "Manual Mode" in resp.json()["detail"] or "Failed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /api/profile (transform_profile integration + PostgREST upsert)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _stub_postgrest(monkeypatch, calls: dict):
    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["params"] = params
        calls["headers"] = headers
        calls["json"] = json
        return _FakeResp(201, [json])

    monkeypatch.setattr(httpx, "post", fake_post)


def _stub_account_id(monkeypatch, account_id: str = "acc-uuid-1"):
    import services.api.routers.profile as profile_router

    captured = {}
    monkeypatch.setattr(profile_router, "_account_id", lambda token: account_id)
    return captured


def test_save_profile_runs_exact_migration_transform(client, rsa_material, monkeypatch):
    import services.api.routers.profile as profile_router
    from migration.transform import transform_profile

    calls: dict = {}
    monkeypatch.setattr(profile_router, "_account_id", lambda token: "acc-uuid-1")
    _stub_postgrest(monkeypatch, calls)

    token = mint_token(rsa_material[0])
    resp = client.put("/api/profile", json=V2_PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text

    row = calls["json"]
    # account scoping + upsert conflict target
    assert row["account_id"] == "acc-uuid-1"
    assert calls["params"] == {"on_conflict": "account_id"}
    # the caller's OWN token is forwarded (RLS, DEC-014)
    assert calls["headers"]["Authorization"] == f"Bearer {token}"
    assert "merge-duplicates" in calls["headers"]["Prefer"]

    # EXACT transform parity: compare with a direct call on the same input
    expected = transform_profile({
        "career_stage": V2_PAYLOAD["career_stage"],
        "personal_identity": V2_PAYLOAD["personal_identity"],
        "education": V2_PAYLOAD["education"],
        "experience": V2_PAYLOAD["experience"],
        "skills": V2_PAYLOAD["skills"],
        "languages": V2_PAYLOAD["languages"],
        "certifications": V2_PAYLOAD["certifications"],
        "profile_method": "ai",
        "onboarding_completed": True,
        "original_cv_files": V2_PAYLOAD["saved_files"],
    })
    for key, value in expected.items():
        assert row[key] == value, f"transform mismatch on {key}"

    # V2 manual identity keys survive (not dropped)
    assert row["identity"]["first_name"] == "Aymen"
    assert row["identity"]["nationality"] == "Tunisian"
    assert row["identity"]["requires_visa_sponsorship"] is True
    # skills reclassified into the V3 taxonomy (migration rules)
    assert row["skills"]["TECHNICAL"] == ["Python", "SQL", "Odoo"]
    assert row["skills"]["MANAGEMENT"] == ["Scrum"]
    assert row["skills"]["CORE"] == ["Communication"]
    # strong evidence: currently_working active role (migration rule)
    assert row["strong_evidence"] is True
    # CV metadata only (ISS-006): count kept, base64/content never persisted
    assert row["original_cv_count"] == 1
    assert "storage_ref" not in json.dumps(row) or "content_base64" not in json.dumps(row)
    # V2 onboarding metadata preserved
    assert row["profile_method"] == "ai"
    assert row["onboarding_completed"] is True


def test_save_profile_rejects_unknown_career_stage(client, rsa_material, monkeypatch):
    import services.api.routers.profile as profile_router

    monkeypatch.setattr(profile_router, "_account_id", lambda token: "acc-uuid-1")
    token = mint_token(rsa_material[0])
    bad = dict(V2_PAYLOAD, career_stage="Interstellar Overlord")
    resp = client.put("/api/profile", json=bad, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


def test_save_profile_requires_identity(client, rsa_material, monkeypatch):
    import services.api.routers.profile as profile_router

    monkeypatch.setattr(profile_router, "_account_id", lambda token: "acc-uuid-1")
    token = mint_token(rsa_material[0])
    resp = client.put("/api/profile", json={"career_stage": ""}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


def test_save_profile_requires_auth(client):
    resp = client.put("/api/profile", json=V2_PAYLOAD)
    assert resp.status_code == 401


def test_save_profile_upsert_failure_maps_to_502(client, rsa_material, monkeypatch):
    import services.api.routers.profile as profile_router

    monkeypatch.setattr(profile_router, "_account_id", lambda token: "acc-uuid-1")

    def failing_post(url, params=None, headers=None, json=None, timeout=None):
        return _FakeResp(403, {"message": "RLS violation"})

    monkeypatch.setattr(httpx, "post", failing_post)
    token = mint_token(rsa_material[0])
    resp = client.put("/api/profile", json=V2_PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 502


