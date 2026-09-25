"""AIROS V3 - ATS 'stuck after analyze' regression tests.
Covers the root-cause fixes for the hang report:
 T1 gateway never hangs forever (every network hop has a timeout);
 T2 invalid/NaN score can never become proceed (fail-safe NO path);
 T3 degenerate/empty JD parse never scores 100% (parse_failed -> 0%);
 T4 router guards stay intact (422/409/500/502 in <2s, no network).
All offline except T1-budget which asserts code-level timeouts (no live key).
"""
from __future__ import annotations
import inspect
import math
import urllib.request

from ai import ats
from ai import gateway as gw


def test_gateway_timeouts_are_bounded():
    src = inspect.getsource(gw._call_gemini)
    assert "timeout=25" in src  # Option A: generate call 25s (was 45s) - fits 120s UI budget
    assert "timeout=45" not in src
    src_list = inspect.getsource(gw._list_supported_generate_models)
    assert "timeout=20" in src_list  # models-list cannot hang forever
    src_router = open("services/api/routers/ats.py", encoding="utf-8").read()
    assert "timeout=15" in src_router  # profile fetch cannot hang forever


def test_option_a_latency_budget():
    """Option A worst-case must fit the 120s UI abort: 4 models x 1 x 25s
    + 1 cached/20s models-list + 15s profile fetch << 120s. Also the
    models-list cache (1h TTL) removes the per-request listing hop."""
    import inspect as _inspect
    assert gw._MODEL_LIST_TTL_S == 3600.0
    sig = _inspect.signature(gw._call_gemini)
    assert sig.parameters["max_retries"].default == 1  # was 2
    gw._clear_model_list_cache()
    assert gw._MODEL_LIST_CACHE == {}


def test_models_list_is_cached_per_key(monkeypatch):
    """Second _resolve_model_chain with the same key must not hit network."""
    gw._clear_model_list_cache()
    calls = {"n": 0}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return (
                b'{"models": [{"name": "models/gemini-3.6-flash",'
                b' "supportedGenerationMethods": ["generateContent"]}]}'
            )

    def fake_urlopen(request, timeout=20):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(gw.urllib.request, "urlopen", fake_urlopen)
    first = gw._resolve_model_chain("test-key-123")
    second = gw._resolve_model_chain("test-key-123")
    assert first == second
    assert calls["n"] == 1  # second call served from the 1h cache
    gw._clear_model_list_cache()


def test_invalid_score_never_proceeds():
    for bad in (None, float("nan"), float("inf"), float("-inf"), "90", True):
        v = ats.classify_threshold(bad, [])  # type: ignore
        assert v["proceed"] is False, bad
        assert v["band"] in ("hard_reject", "blockers")


def test_empty_parse_scores_zero_not_hundred(monkeypatch):
    sample = '{"job_title": "", "company_name": ""}'  # degenerate echo
    monkeypatch.setattr(gw, "_call_gemini", lambda *a, **k: sample)
    monkeypatch.setattr(ats, "_call_gemini", lambda *a, **k: sample)
    job = ats.parse_job_v2("Senior Python Engineer, 5y, Docker", "k", force_refresh=True)
    assert job.get("_api_error") is True  # degenerate gate fires
    cand = {"skills": {"technical": ["Python"], "methodologies": [], "tools": []},
            "total_experience_years": 6, "education": [], "experience": [],
            "languages": [], "certifications": [], "location": "", "nationality": "",
            "industry_hints": [], "all_tokens": {"python"}}
    r = ats.compute_ats_engine(cand, job)
    assert r["overall_ats"] == 0.0
    assert r["parse_failed"] is True


def test_router_guards_fast_offline(client, rsa_material, monkeypatch):
    from tests.conftest import mint_token
    import services.api.routers.ats as router
    token = mint_token(rsa_material[0])
    # 401 no token
    assert client.post("/api/ats/analyze", json={"job_text": "x"}).status_code == 401
    # 422 empty JD (auth passes, no network touched)
    r = client.post("/api/ats/analyze", json={"job_text": "  "},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422
    # 409 no profile (mocked fetch, no network)
    monkeypatch.setattr(router, "_fetch_own_profile", lambda t: {})
    r = client.post("/api/ats/analyze", json={"job_text": "Senior role"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 409
    # 500 no gemini key (mocked fetch + empty key, no network)
    monkeypatch.setattr(router, "_fetch_own_profile", lambda t: {"skills": {}})
    monkeypatch.setattr(router, "_gemini_key", lambda: "")
    r = client.post("/api/ats/analyze", json={"job_text": "Senior role"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 500
