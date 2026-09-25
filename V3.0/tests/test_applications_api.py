"""AIROS V3 - Application workspace API tests (CHG-018).

Offline, DB-free (same philosophy as the rest of the suite):
- real RS256 tokens via the conftest fixtures, JWKS patched;
- PostgREST mocked at the httpx transport boundary with an in-memory store,
  asserting THE CALLER'S TOKEN is forwarded on every request (RLS path);
- Gemini mocked at the router boundary for the document engine;
- generated documents land in a tmp uploads dir (monkeypatch.chdir).
"""

from __future__ import annotations

import json
import zipfile
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import mint_token


class FakeResp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeStore:
    """Minimal in-memory PostgREST: per-account rows keyed by table."""

    def __init__(self):
        self.tables: dict = {name: [] for name in
                             ("accounts", "profiles", "companies", "contacts", "jobs",
                              "applications", "documents")}
        self.calls: list = []

    # -- request handling --------------------------------------------------
    def handle(self, method: str, url: str, params=None, headers=None, json_body=None):
        table = url.rsplit("/", 1)[-1]
        params = dict(params or {})
        self.calls.append({"method": method, "table": table, "params": params,
                           "auth": (headers or {}).get("Authorization", "")})

        rows = self.tables.setdefault(table, [])
        if method == "GET":
            out = rows
            for key, value in params.items():
                if key in ("select", "limit", "order", "on_conflict"):
                    continue
                if value.startswith("eq."):
                    out = [r for r in out if str(r.get(key)) == value[3:]]
                elif value.startswith("ilike."):
                    out = [r for r in out if value[6:].strip("%").lower()
                           in str(r.get(key, "")).lower()]
                elif value.startswith("in.("):
                    wanted = set(value[4:-1].split(","))
                    out = [r for r in out if str(r.get(key)) in wanted]
                elif value.startswith("like."):
                    import re as _re
                    pattern = _re.escape(value[5:]).replace(r"\*", ".*")
                    out = [r for r in out
                           if _re.fullmatch(pattern, str(r.get(key, "")))]
            if params.get("order", "").startswith("uploaded_at.desc"):
                out = sorted(out, key=lambda r: r.get("uploaded_at", ""), reverse=True)
            limit = params.get("limit")
            out = out if limit is None else out[: int(limit)]
            return FakeResp(200, out)

        if method == "POST":
            row = dict(json_body or {})
            row.setdefault("id", f"{table}-uuid-{len(rows) + 1}")
            rows.append(row)
            return FakeResp(201, [row])

        if method == "PATCH":
            out = list(rows)
            for key, value in params.items():
                if value.startswith("eq."):
                    out = [r for r in out if str(r.get(key)) == value[3:]]
            for row in out:
                row.update(json_body or {})
            return FakeResp(200, out)

        return FakeResp(405, {"message": "unsupported"})


@pytest.fixture()
def store(monkeypatch):
    """Wire httpx.get/post/patch to the in-memory store + capture the bearer."""
    import services.api.routers.applications as apps_router

    fake = FakeStore()
    fake.tables["accounts"].append({"id": "acct-uuid-1"})
    # Minimal caller-owned profile so the document engine's profile gate passes
    # (build_candidate_json tolerates the missing optional sections).
    fake.tables["profiles"].append({
        "id": "profiles-uuid-1",
        "identity": {"first_name": "Test", "last_name": "User"},
        "skills": {"TECHNICAL": ["Python", "SQL"]},
        "education": [], "experience": [], "languages": [],
    })

    def fake_get(url, params=None, headers=None, timeout=None):
        return fake.handle("GET", url, params=params, headers=headers)

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        return fake.handle("POST", url, params=params, headers=headers, json_body=json)

    def fake_patch(url, params=None, headers=None, json=None, timeout=None):
        return fake.handle("PATCH", url, params=params, headers=headers, json_body=json)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "patch", fake_patch)
    monkeypatch.setattr(apps_router, "_account_id", lambda token: "acc-uuid-1")
    return fake


@pytest.fixture()
def token(rsa_material):
    private_pem, _ = rsa_material
    return mint_token(private_pem)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


ANALYSIS = {
    "ats_score": 82,
    "sub_scores": {"skills": 80, "experience": 90},
    "gap_analysis": ["German C1"],
    "hits": ["Python", "SQL"],
    "evidence": [{"item": "Python", "level": 4, "stars": "★★★★☆"}],
    "decision": "Strong match",
    "parsed_job": {
        "job_title": "Data Engineer",
        "company_name": "Acme",
        "location": "Berlin",
        "country": "Germany",
        "company_website": "https://acme.example",
        "industry": "Tech",
    },
    "verdict": {"band": "manual", "proceed": True},
}


# ---------------------------------------------------------------- auth guard
def test_jobs_endpoint_requires_auth(client):
    resp = client.post("/api/applications/jobs", json={})
    assert resp.status_code == 401


# ---------------------------------------------------------------- save job
def test_save_analyzed_job_creates_company_job_and_contact(client, store, token):
    resp = client.post(
        "/api/applications/jobs",
        json={
            "analysis": ANALYSIS,
            "original_jd": "Data Engineer at Acme...",
            "contact": {"name": "Anna Muller", "email": "anna@acme.example",
                        "position": "Talent Acquisition", "confidence": "High"},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job"]["job_id"] == "JOB-2026-000001"
    assert body["job"]["company_id"] == body["company"]["company_id"] == "COMP-2026-000001"
    assert body["job"]["ats_score"] == 82
    assert body["job"]["contact_ids"] == [body["contact"]["contact_id"]]
    assert body["contact"]["contact_id"] == "CONT-2026-000001"
    assert body["contact"]["position"] == "Talent Acquisition"  # stored as position ...
    assert body["contact"]["contact_type"] == "HR Recruiter"    # ... type default kept

    # every request forwarded the CALLER's token (RLS boundary, DEC-013/014)
    assert store.calls and all(c["auth"] == f"Bearer {token}" for c in store.calls)


def test_save_analyzed_job_generic_email_downgraded(client, store, token):
    resp = client.post(
        "/api/applications/jobs",
        json={
            "analysis": ANALYSIS,
            "original_jd": "JD",
            "contact": {"name": "HR Team", "email": "careers@acme.example"},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    contact = resp.json()["contact"]
    assert contact["contact_type"] == "General"
    assert contact["confidence"] == "Low"


def test_save_analyzed_job_reuses_company_by_name(client, store, token):
    for _ in range(2):
        resp = client.post(
            "/api/applications/jobs",
            json={"analysis": ANALYSIS, "original_jd": "JD again"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
    body = resp.json()
    assert body["company"]["company_id"] == "COMP-2026-000001"  # reused, not duplicated
    assert body["job"]["job_id"] == "JOB-2026-000002"           # sequential job id


def test_save_analyzed_job_requires_parsed_job(client, token):
    resp = client.post(
        "/api/applications/jobs",
        json={"analysis": {"ats_score": 10}, "original_jd": "JD"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_add_contact_to_job_links_it(client, store, token):
    first = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    resp = client.post(
        f"/api/applications/jobs/{first['job']['job_id']}/contacts",
        json={"name": "Bob", "email": "bob@acme.example", "contact_type": "Hiring Manager"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["contact_ids"] == [resp.json()["contact"]["contact_id"]]


# ---------------------------------------------------------------- documents
GENERATED = {
    "cv": {"full_text": "TAILORED CV TEXT", "skills": {"technical": ["Python"]}},
    "cover_letter": {"full_text": "DEAR HIRING TEAM"},
    "recruiter_email": {"required": True, "to": "anna@acme.example",
                        "subject": "Application", "body": "Hello"},
    "optimization_report": {"target_keywords_used": ["python"],
                            "gaps_not_claimed": ["German C1"], "evidence_based": True},
    "recruiter_contact": {"contact_id": "CONT-2026-000001"},
}
VALIDATION = {"status": "improved", "improvement": 6, "original_ats": 82,
              "tailored_ats": 88, "needs_review": False,
              "message": "+6 points"}


def _generate_documents_call(client, store, token, monkeypatch, tmp_path):
    import services.api.routers.applications as apps_router

    monkeypatch.chdir(tmp_path)  # generated docs land in tmp
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(GENERATED)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))

    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD",
                              "contact": {"name": "Anna", "email": "anna@acme.example"}},
                        headers=_auth(token)).json()
    resp = client.post(f"/api/applications/jobs/{saved['job']['job_id']}/documents",
                       json={}, headers=_auth(token))
    return saved, resp


def test_generate_documents_persists_files_and_metadata(client, store, token, monkeypatch, tmp_path):
    saved, resp = _generate_documents_call(client, store, token, monkeypatch, tmp_path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated"]["cv"]["full_text"] == "TAILORED CV TEXT"
    assert body["validation"]["status"] == "improved"
    # cv + cover_letter + recruiter_email persisted (metadata-only rows, ISS-006)
    assert {"cv", "cover_letter", "recruiter_email"} <= {
        k.rsplit("_", 1)[0] for k in body["docs"] if k.endswith("_path")}
    # Key parity: the recruiter email is ALSO exposed under the short
    # email_* keys used by the frontend PrepareTab and _latest_job_documents().
    assert body["docs"]["email_document_id"]
    assert body["docs"]["email_path"]
    files = list((tmp_path / "data" / "uploads").rglob("*.txt"))
    assert len(files) == 3
    assert any(f.name.startswith("cv_") for f in files)
    assert len(store.tables["documents"]) == 3


def test_generate_documents_requires_gemini_key(client, store, token, monkeypatch, tmp_path):
    import services.api.routers.applications as apps_router
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    resp = client.post(f"/api/applications/jobs/{saved['job']['job_id']}/documents",
                       json={}, headers=_auth(token))
    assert resp.status_code == 500


def test_generate_documents_without_reliable_rh_skips_email_but_not_workflow(
        client, store, token, monkeypatch, tmp_path):
    """JD without RH data (manual-test feedback): the document engine must still
    produce the tailored CV + cover letter; ONLY the recruiter email is skipped
    and the endpoint never blocks the workflow."""
    import services.api.routers.applications as apps_router

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    no_rh_generated = {
        "cv": {"full_text": "TAILORED CV TEXT", "skills": {"technical": ["Python"]}},
        "cover_letter": {"full_text": "DEAR HIRING TEAM"},
        # The real engine forces required=False when no reliable RH contact.
        "recruiter_email": {"required": False, "to": "", "subject": "", "body": "",
                            "message": "No reliable individual recruiter email was identified."},
        "optimization_report": {"target_keywords_used": ["python"],
                                "gaps_not_claimed": [], "evidence_based": True},
        "recruiter_contact": {},
    }
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(no_rh_generated)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))

    # Save the job WITHOUT any recruiter contact.
    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    assert saved["job"]["contact_ids"] == []

    resp = client.post(f"/api/applications/jobs/{saved['job']['job_id']}/documents",
                       json={"generate_recruiter_email": False}, headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Explicit no-RH signals: the RH mailing feature is removed, nothing blocks.
    assert body["recruiter_email_skipped"] is True
    assert body["reliable_contact"] == {}
    assert body["generated"]["recruiter_email"]["required"] is False
    # CV + cover letter persisted; the recruiter email did NOT create a record.
    assert body["docs"]["cv_document_id"]
    assert body["docs"]["cover_letter_document_id"]
    assert not body["docs"].get("email_document_id")
    assert len(store.tables["documents"]) == 2
    files = list((tmp_path / "data" / "uploads").rglob("*.txt"))
    assert len(files) == 2


# --------------------------------------------------- renditions (CHG-026)
RENDERABLE_GENERATED = {
    "cv": {
        "summary": "ERP & IT Programme Manager with 16+ years of experience.",
        "experience": [
            {"title": "Program Manager", "company": "IPACT", "start_date": "01.2022",
             "end_date": "Present", "description": "Led digital transformation programs.",
             "achievements": ["Delivered a multi-tenant SaaS platform across 4 countries."]},
        ],
        "skills": {"technical": ["Python", "SQL"], "methodologies": ["Agile"], "tools": ["Docker"]},
        "full_text": "TAILORED CV TEXT",
    },
    "cover_letter": {
        "greeting": "Dear Hiring Team,",
        "opening": "I am applying for the ERP Implementation Project Manager role.",
        "body": "I lead ERP implementation projects with hybrid PMO governance.",
        "closing": "Kind regards,",
        "full_text": "DEAR HIRING TEAM",
    },
    "recruiter_email": {"required": False, "to": "", "subject": "", "body": "", "message": "skipped"},
    "optimization_report": {"target_keywords_used": [], "gaps_not_claimed": [], "evidence_based": True},
    "recruiter_contact": {},
}


def _generate_renderable_documents(client, store, token, monkeypatch, tmp_path):
    import services.api.routers.applications as apps_router

    monkeypatch.chdir(tmp_path)  # renditions land in tmp
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(RENDERABLE_GENERATED)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))
    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    resp = client.post(f"/api/applications/jobs/{saved['job']['job_id']}/documents",
                       json={"generate_recruiter_email": False}, headers=_auth(token))
    return resp


def test_generate_documents_renders_ready_to_send_docx(
        client, store, token, monkeypatch, tmp_path):
    resp = _generate_renderable_documents(client, store, token, monkeypatch, tmp_path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rendering = body["rendering"]
    assert set(rendering["documents"]) == {"cv", "cover_letter"}
    for doc_type in ("cv", "cover_letter"):
        entry = rendering["documents"][doc_type]
        assert entry["ok"] is True, entry["errors"]
        assert entry["docx"]["saved_as"].endswith(".docx")
    # text documents remain canonical; renditions are files, NOT extra rows
    assert len(store.tables["documents"]) == 2
    docx_files = list((tmp_path / "data" / "uploads").rglob("*.docx"))
    assert len(docx_files) == 2
    # every DOCX is a real OOXML container
    for path in docx_files:
        assert zipfile.is_zipfile(path)


def test_document_rendition_download_endpoint(client, store, token, monkeypatch, tmp_path):
    resp = _generate_renderable_documents(client, store, token, monkeypatch, tmp_path)
    body = resp.json()
    doc_id = body["docs"]["cv_document_id"]

    # DOCX rendition: auth-gated, right media type, real OOXML container
    got = client.get(f"/api/applications/documents/{doc_id}/file?format=docx",
                     headers=_auth(token))
    assert got.status_code == 200, got.text
    assert got.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert got.content[:2] == b"PK"  # OOXML zip container magic
    assert "attachment" in got.headers.get("content-disposition", "")
    assert got.headers.get("content-disposition", "").endswith('.docx"')

    # unknown format is a clean 422
    bad = client.get(f"/api/applications/documents/{doc_id}/file?format=exe",
                     headers=_auth(token))
    assert bad.status_code == 422

    # PDF without LibreOffice: actionable 409, never a silent failure
    if not body["rendering"]["pdf_available"]:
        pdf = client.get(f"/api/applications/documents/{doc_id}/file?format=pdf",
                         headers=_auth(token))
        assert pdf.status_code == 409
        assert "LibreOffice" in pdf.json()["detail"]


def test_document_rendition_requires_authentication(client, store, token, monkeypatch, tmp_path):
    resp = _generate_renderable_documents(client, store, token, monkeypatch, tmp_path)
    doc_id = resp.json()["docs"]["cv_document_id"]
    assert client.get(
        f"/api/applications/documents/{doc_id}/file?format=docx"
    ).status_code in (401, 403)


# ---------------------------------------------------------------- confirm
def test_confirm_application_cancelled_creates_no_record(client, store, token):
    resp = client.post("/api/applications",
                       json={"job_id": "JOB-2026-000001", "decision": "cancelled"},
                       headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"created": False, "application_id": ""}
    assert store.tables["applications"] == []


def test_confirm_application_sent_creates_applied_record(client, store, token):
    client.post("/api/applications/jobs",
                json={"analysis": ANALYSIS, "original_jd": "JD",
                      "contact": {"name": "Anna", "email": "anna@acme.example"}},
                headers=_auth(token))
    resp = client.post("/api/applications",
                       json={"job_id": "JOB-2026-000001", "decision": "sent",
                             "channel": "Direct Email to Recruiter",
                             "application_date": "2026-09-09", "notes": "done"},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["application_id"] == "APP-2026-000001"
    record = body["application"]
    assert record["status"] == "APPLIED"
    assert record["recruiter_name"] == "Anna"
    assert record["channel"] == "Direct Email to Recruiter"
    assert record["timeline"][0]["status"] == "APPLIED"
    assert record["follow_up_checkpoint"]      # Rule 3 checkpoint set
    assert record["job_closing_date"] == ""

    # RH fix: the Track detail must surface the SAME recruiter (no more
    # "missing RH" after confirm) via the enriched reliable_contact.
    detail = client.get("/api/applications/APP-2026-000001", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    enriched = detail.json()["application"]
    assert enriched["reliable_contact"]["email"] == "anna@acme.example"
    assert enriched["reliable_contact"]["name"] == "Anna"
    assert any(c["contact_id"] == enriched["reliable_contact"]["contact_id"]
               for c in enriched["contacts"])
    assert enriched["recruiter_name"] == "Anna"


def test_confirm_application_requires_channel_when_sent(client, store, token):
    client.post("/api/applications/jobs",
                json={"analysis": ANALYSIS, "original_jd": "JD"}, headers=_auth(token))
    resp = client.post("/api/applications",
                       json={"job_id": "JOB-2026-000001", "decision": "sent"},
                       headers=_auth(token))
    assert resp.status_code == 422


# ---------------------------------------------------------------- tracking
def _trackable_app_id(client, store, token) -> str:
    """Confirm an announcement-today job end-to-end so tracking transitions hold."""
    closing = (date.today() + timedelta(days=30)).isoformat()
    parsed = dict(ANALYSIS["parsed_job"], publication_date=date.today().isoformat(),
                  closing_date=closing)
    analysis = {
        "ats_score": 90,
        "parsed_job": parsed,
    }
    client.post("/api/applications/jobs",
                json={"analysis": analysis, "original_jd": "JD"}, headers=_auth(token))
    return client.post("/api/applications",
                       json={"job_id": "JOB-2026-000001", "decision": "sent",
                             "channel": "LinkedIn Easy Apply"},
                       headers=_auth(token)).json()["application_id"]


def test_save_job_maps_502_to_missing_workspace_tables(client, store, token, monkeypatch):
    """PGRST205 (PostgREST schema cache has no workspace tables) must surface
    as an actionable 409 telling the operator to apply 0006/0007 — the live
    symptom the user reported as 'upstream PostgREST error on companies: 404'.
    """
    import services.api.routers.applications as router

    class _Resp:
        status_code = 404
        text = "PGRST205"

        def json(self):
            return {"code": "PGRST205", "message": "schema cache"}

    real_get = router.httpx.get

    def wrapper(url, params=None, headers=None, timeout=None):
        if url.endswith("/companies"):
            return _Resp()
        return real_get(url, params=params, headers=headers, timeout=timeout)

    monkeypatch.setattr(router.httpx, "get", wrapper)
    resp = client.post("/api/applications/jobs",
                       json={"analysis": ANALYSIS, "original_jd": "JD"},
                       headers=_auth(token))
    assert resp.status_code == 409, resp.text
    assert "0006_application_workspace" in resp.json()["detail"]
    assert "companies" in resp.json()["detail"]


def test_tracking_full_lifecycle_applied_to_offer(client, store, token):
    _trackable_app_id(client, store, token)
    app_id = "APP-2026-000001"

    detail = client.get(f"/api/applications/{app_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    app = detail.json()["application"]
    assert app["status"] == "APPLIED"
    assert "INTERVIEW" in app["allowed_transitions"]
    assert app["next_action"]            # non-empty single next action
    assert app["follow_up_draft"]["message"].startswith(  # draft ready even pre-follow-up
        "Subject: Follow-up on Data Engineer application")
    # RH fix: detail enriches the RH + company context for the Track UI.
    assert app["reliable_contact"] == {}
    assert app["contacts"] == []
    assert app["company"]["name"] == "Acme"  # company_name from the JD parse

    move = client.post(f"/api/applications/{app_id}/status",
                       json={"new_status": "INTERVIEW", "note": "screening call"},
                       headers=_auth(token))
    assert move.status_code == 200, move.text
    assert move.json()["application"]["status"] == "INTERVIEW"

    iv = client.post(f"/api/applications/{app_id}/interview",
                     json={"round_no": 1, "scheduled_at": "2099-01-15 10:00",
                           "mode": "Video Call", "notes": ""},
                     headers=_auth(token))
    assert iv.status_code == 200, iv.text
    scheduled = [r for r in iv.json()["application"]["interviews"]
                 if r["round"] == 1 and r["scheduled_at"] == "2099-01-15 10:00"]
    assert scheduled  # round 1 persisted; pending_interview stays None once scheduled

    # Follow-ups live in WAITING: the screener loop APPLIED -> WAITING ->
    # INTERVIEW exercises exactly that (V2: APPLIED can move to WAITING).
    fresh = client.post("/api/applications/jobs",
                        json={"analysis": {"ats_score": 90,
                                           "parsed_job": dict(ANALYSIS["parsed_job"])},
                              "original_jd": "JD 2"}, headers=_auth(token)).json()["job"]
    app2 = client.post("/api/applications",
                       json={"job_id": fresh["job_id"], "decision": "sent",
                             "channel": "LinkedIn Easy Apply"},
                       headers=_auth(token)).json()["application_id"]
    w = client.post(f"/api/applications/{app2}/status",
                    json={"new_status": "WAITING", "note": "waiting for feedback"},
                    headers=_auth(token))
    assert w.status_code == 200, w.text

    fu = client.post(f"/api/applications/{app2}/followup",
                     json={"channel": "Email", "contacted_at": "2026-09-09",
                           "note": "checking in"},
                     headers=_auth(token))
    assert fu.status_code == 200, fu.text
    assert len(fu.json()["application"]["follow_ups"]) == 1

    # Primary loop continues on the first application: INTERVIEW through OFFER.
    fwd = client.post(f"/api/applications/{app_id}/status",
                      json={"new_status": "INTERVIEW", "note": "interview invite"},
                      headers=_auth(token))
    assert fwd.status_code == 200, fwd.text

    resp = client.post(f"/api/applications/{app_id}/response",
                       json={"response_type": "INTERVIEW_REQUEST",
                             "channel": "Email", "responded_on": "2026-09-09"},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["application"]["recruiter_responses"]) == 1

    offer = client.post(f"/api/applications/{app_id}/status",
                        json={"new_status": "OFFER", "note": ""}, headers=_auth(token))
    assert offer.status_code == 200, offer.text
    assert offer.json()["application"]["status"] == "OFFER"
    assert offer.json()["application"]["next_action"]["action"] == "Close the application"


def test_tracking_rejects_illegal_transition(client, store, token):
    _trackable_app_id(client, store, token)
    resp = client.post("/api/applications/APP-2026-000001/status",
                       json={"new_status": "OFFER", "note": ""}, headers=_auth(token))
    assert resp.status_code == 422  # APPLIED -> OFFER is not a manual transition


def test_tracking_scheduling_empty_interview_datetime_is_rejected(client, store, token):
    _trackable_app_id(client, store, token)
    resp = client.post("/api/applications/APP-2026-000001/interview",
                       json={"round_no": 1, "scheduled_at": "",
                             "mode": "Video Call", "notes": ""},
                       headers=_auth(token))
    assert resp.status_code == 422  # V2: interview date/time is mandatory


def test_tracking_response_refused_closes_record(client, store, token):
    _trackable_app_id(client, store, token)
    resp = client.post("/api/applications/APP-2026-000001/response",
                       json={"response_type": "REFUSED", "channel": "Email",
                             "responded_on": "2026-09-09"},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["application"]["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# CHG-023 - recruiter hardening + workspace approval + timestamps
# ---------------------------------------------------------------------------
def _analysis_with_recruiter():
    parsed = dict(ANALYSIS["parsed_job"])
    parsed["recruiter_contact"] = {
        "name": "Anna Mueller",
        "position": "Senior Talent Acquisition",
        "email": "anna.mueller@acme.example",
        "linkedin_url": "https://linkedin.com/in/anna-mueller",
        "phone": "+49 170 1234567",
    }
    return dict(ANALYSIS, parsed_job=parsed)


def test_save_job_auto_persists_parsed_recruiter_when_contact_omitted(
        client, store, token):
    """No contact in the request -> the JD-parsed recruiter is persisted
    server-side (CHG-023 hardening: 'RH defined in JD' is never dropped)."""
    resp = client.post("/api/applications/jobs",
                       json={"analysis": _analysis_with_recruiter(), "original_jd": "JD"},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    contact = body["contact"]
    assert contact is not None
    assert contact["name"] == "Anna Mueller"
    assert contact["email"] == "anna.mueller@acme.example"
    assert contact["phone"] == "+49 170 1234567"
    assert contact["linkedin_url"] == "https://linkedin.com/in/anna-mueller"
    assert contact["source"] == "JD"
    assert body["job"]["contact_ids"] == [contact["contact_id"]]


def test_save_job_preserves_partial_recruiter_contact(client, store, token):
    """A partial match (name-only) is preserved, not dropped."""
    resp = client.post("/api/applications/jobs",
                       json={"analysis": ANALYSIS, "original_jd": "JD",
                             "contact": {"name": "Anna Muller"}},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    contact = resp.json()["contact"]
    assert contact["name"] == "Anna Muller"
    assert contact["email"] == ""  # partial kept as-is
    assert resp.json()["job"]["contact_ids"] == [contact["contact_id"]]


# ------------------------------------------------------- PGRST204 resilience
def test_save_job_survives_missing_phone_column(client, store, token, monkeypatch):
    """CHG-024: PGRST204 (migration 0008 'phone' column not applied to the live
    DB) must NOT fail the Save Job + Company + Recruiter step. The insert
    retries WITHOUT the unknown column, the response carries schema_warning so
    the dropped value is surfaced, and the job itself is saved."""
    real_post = httpx.post

    def pgrst204_then_real(url, params=None, headers=None, json=None, timeout=None):
        if url.endswith("/contacts") and json and "phone" in json:
            payload = {"code": "PGRST204", "message":
                       "Could not find the 'phone' column of 'contacts' in the schema cache"}
            return FakeResp(400, payload)
        return real_post(url, params=params, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(httpx, "post", pgrst204_then_real)

    resp = client.post("/api/applications/jobs",
                       json={"analysis": ANALYSIS, "original_jd": "JD",
                             "contact": {"name": "Anna", "email": "anna@acme.example",
                                         "phone": "+49 170 1234567"}},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The job + contact are saved (RH data without phone is NOT lost); the
    # dropped phone value is reported, never silently discarded.
    assert body["contact"]["name"] == "Anna"
    assert body["job"]["contact_ids"] == [body["contact"]["contact_id"]]
    assert "0008_workspace_approval" in body.get("schema_warning", "")
    assert "phone" in body.get("schema_warning", "")


def test_save_job_pgrst204_unknown_column_not_in_row_is_actionable(
        client, store, token, monkeypatch):
    """When PGRST204 names a column the request does NOT even carry, the save
    fails loudly with the migration-0008 advice instead of the raw PGRST text."""
    real_post = httpx.post

    def pgrst204_always(url, params=None, headers=None, json=None, timeout=None):
        if url.endswith("/jobs"):
            payload = {"code": "PGRST204", "message":
                       "Could not find the 'docs_approved_at' column of 'jobs' in the schema cache"}
            return FakeResp(400, payload)
        return real_post(url, params=params, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(httpx, "post", pgrst204_always)

    resp = client.post("/api/applications/jobs",
                       json={"analysis": ANALYSIS, "original_jd": "JD"},
                       headers=_auth(token))
    assert resp.status_code == 502
    assert "0008_workspace_approval" in resp.json()["detail"]


def test_generate_documents_persists_docs_generated_at_on_job(
        client, store, token, monkeypatch, tmp_path):
    import services.api.routers.applications as apps_router
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(GENERATED)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))

    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    client.post(f"/api/applications/jobs/{saved['job']['job_id']}/documents",
                json={}, headers=_auth(token))
    detail = client.get(f"/api/applications/jobs/{saved['job']['job_id']}",
                        headers=_auth(token)).json()
    assert detail["docs_generated_at"], "generation timestamp not persisted on the job"
    # The workspace detail reconstructs the Prepare input shape {job, company, contact}.
    assert detail["job"]["job_id"] == saved["job"]["job_id"]
    assert detail["company"]["company_id"] == saved["company"]["company_id"]
def test_approve_documents_captures_exact_timestamp(client, store, token, monkeypatch, tmp_path):
    import services.api.routers.applications as apps_router
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(GENERATED)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))

    saved = client.post("/api/applications/jobs",
                        json={"analysis": ANALYSIS, "original_jd": "JD"},
                        headers=_auth(token)).json()
    job_id = saved["job"]["job_id"]
    client.post(f"/api/applications/jobs/{job_id}/documents", json={}, headers=_auth(token))

    resp = client.post(f"/api/applications/jobs/{job_id}/documents/approve",
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["docs_generated_at"]
    assert body["docs_approved_at"]
    assert isinstance(body["time_consumed_min"], int)

    detail = client.get(f"/api/applications/jobs/{job_id}", headers=_auth(token)).json()
    assert detail["docs_approved_at"] == body["docs_approved_at"]


def test_jobs_list_endpoint_returns_saved_jobs(client, store, token):
    client.post("/api/applications/jobs",
                json={"analysis": ANALYSIS, "original_jd": "JD"},
                headers=_auth(token))
    resp = client.get("/api/applications/jobs", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["ats_score"] == ANALYSIS["ats_score"]


def test_confirm_copies_workspace_timestamps_and_recruiter_snapshot(
        client, store, token, monkeypatch, tmp_path):
    """The confirmed application carries docs_generated_at + docs_approved_at
    (exact system datetimes) and the recruiter_interactions snapshot."""
    import services.api.routers.applications as apps_router
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(apps_router, "generate_application_documents",
                        lambda *a, **k: json.loads(json.dumps(GENERATED)))
    monkeypatch.setattr(apps_router, "validate_generated_documents",
                        lambda *a, **k: dict(VALIDATION))

    saved = client.post("/api/applications/jobs",
                        json={"analysis": _analysis_with_recruiter(), "original_jd": "JD",
                              "contact": {"name": "Anna Mueller",
                                          "email": "anna.mueller@acme.example"}},
                        headers=_auth(token)).json()
    job_id = saved["job"]["job_id"]
    client.post(f"/api/applications/jobs/{job_id}/documents", json={}, headers=_auth(token))
    client.post(f"/api/applications/jobs/{job_id}/documents/approve", headers=_auth(token))

    resp = client.post("/api/applications",
                       json={"job_id": job_id, "decision": "sent",
                             "channel": "Direct Email to Recruiter"},
                       headers=_auth(token))
    assert resp.status_code == 200, resp.text
    app = resp.json()["application"]
    assert app["docs_generated_at"], "docs_generated_at must be carried to the application"
    assert app["docs_approved_at"], "docs_approved_at must be carried to the application"
    # Recruiter snapshot persisted into the JSONB audit trail (never dropped).
    interactions = app["recruiter_interactions"] or []
    assert len(interactions) == 1
    assert interactions[0]["type"] == "recruiter_contact_initial"
    assert interactions[0]["email"] == "anna.mueller@acme.example"
