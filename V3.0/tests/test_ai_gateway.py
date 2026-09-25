"""AIROS V3 - AI Gateway tests (Slice 6, DEC-005/ISS-004).

Verifies the V2-ported Gemini core offline: JSON cleaning/repair, response
post-processing (skills mapping, spoken-language filter), the model fallback
chain, the retry/auth error matrix, and the deterministic failure behavior
(V2 parity: clean error -> Manual Mode, never a silent provider swap).
"""

from __future__ import annotations

import json

import pytest

from ai import gateway
from ai.gateway import GatewayError, _call_gemini, _clean_json_response, _process_extraction


# ---------------------------------------------------------------------------
# JSON cleaning / repair (V2 parity)
# ---------------------------------------------------------------------------

def test_clean_strips_markdown_fences():
    raw = "```json\n{\"a\": 1}\n```"
    assert json.loads(_clean_json_response(raw)) == {"a": 1}


def test_clean_fixes_trailing_commas_and_single_quotes():
    raw = "{'a': [1, 2,], 'b': {'c': 3,}}"
    assert json.loads(_clean_json_response(raw)) == {"a": [1, 2], "b": {"c": 3}}


def test_clean_extracts_biggest_json_block():
    raw = "Here is the result:\n{\"x\": \"y\"}\nHope that helps!"
    assert json.loads(_clean_json_response(raw)) == {"x": "y"}


def test_clean_escapes_newlines_inside_strings():
    raw = '{"summary": "line1\nline2"}'
    parsed = json.loads(_clean_json_response(raw))
    assert parsed["summary"] == "line1\nline2"


def test_clean_repairs_unescaped_interior_quotes():
    # Interior quotes inside a quoted value get escaped (V2 heuristic)
    raw = '{"description": "He said "hi" loudly", "ok": 1}'
    parsed = json.loads(_clean_json_response(raw))
    assert "hi" in parsed["description"]


def test_clean_empty_response_returns_empty_object():
    assert _clean_json_response("") == "{}"


# ---------------------------------------------------------------------------
# Post-processing (V2 parity: skills mapping + language filter)
# ---------------------------------------------------------------------------

def _canned_response() -> str:
    return json.dumps({
        "personal_identity": {"full_name": "Aymen Dr", "email": "a@b.c"},
        "career_stage_suggestion": "Experienced Professional (3–8 years)",
        "education": [{"degree": "Master", "field": "IS", "institution": "UT"}],
        "professional_experience": [{"company": "X", "role": "Engineer"}],
        "technical_skills": ["Python", "Agile", "Docker", "Python"],
        "core_skills": ["Communication"],
        "languages": [
            {"language": "French", "level": "C2"},
            {"language": "Python", "level": "fluent"},
        ],
        "certifications": [{"name": "PMP", "issuer": "PMI", "year": "2020"}],
        "total_experience_years": 5,
    })


def test_process_maps_skills_and_filters_spoken_languages():
    data = _process_extraction(_canned_response())
    assert data["skills"]["technical"] == ["Python", "Docker"]
    assert data["skills"]["methodologies"] == ["Agile"]
    assert data["skills"]["tools"] == []
    assert data["skills"]["core"] == ["Communication"]
    # dedupe happened before mapping
    assert data["technical_skills"] == ["Python", "Agile", "Docker"]
    # programming languages removed from spoken languages
    assert data["languages"] == [{"language": "French", "level": "C2"}]


def test_process_recovered_truncated_json_keeps_defaults():
    # Truncated JSON triggers the V2 second-pass recovery
    raw = '{"technical_skills": ["Python"], "education": [{"degree": "M"}'
    data = _process_extraction(raw)
    assert isinstance(data, dict)


def test_process_normalizes_skills_sections_and_derives_flats():
    # V3: skills_sections is the primary skills output. Normalization strips
    # blank titles/items and drops invalid entries; the flat arrays are
    # derived from the sections when Gemini left them empty.
    raw = json.dumps({
        "skills_sections": [
            {"section_title": " Tools & Technologies ", "items": ["Python", " ", "Docker"]},
            {"section_title": "Soft Skills", "items": ["Leadership"]},
            {"section_title": "", "items": ["Ignored - no title"]},
            {"section_title": "Empty section", "items": []},
            {"not_a_section": True},
        ],
        "languages": [],
    })
    data = _process_extraction(raw)
    assert data["skills"]["sections"] == [
        {"section_title": "Tools & Technologies", "items": ["Python", "Docker"]},
        {"section_title": "Soft Skills", "items": ["Leadership"]},
    ]
    # flat arrays derived from the sections
    assert data["technical_skills"] == ["Python", "Docker"]
    assert data["core_skills"] == ["Leadership"]
    assert data["skills"]["technical"] == ["Python", "Docker"]
    assert data["skills"]["core"] == ["Leadership"]


def test_process_coerces_section_items_objects():
    # Gemini sometimes emits items as objects ({"name": ...}) - coerce, never drop
    raw = json.dumps({
        "skills_sections": [
            {"section_title": "Tools", "items": [{"name": "Python"}, {"skill": "Docker"}, {"x": 1}, 42, " "]},
        ],
    })
    data = _process_extraction(raw)
    assert data["skills"]["sections"] == [{"section_title": "Tools", "items": ["Python", "Docker"]}]


def test_process_derives_missing_core_from_soft_sections():
    # per-array derivation: flats partially present -> only the empty one is derived
    raw = json.dumps({
        "technical_skills": ["Python"],
        "skills_sections": [{"section_title": "Soft Skills", "items": ["Leadership"]}],
    })
    data = _process_extraction(raw)
    assert data["technical_skills"] == ["Python"]      # kept, not overwritten
    assert data["core_skills"] == ["Leadership"]       # derived from the soft section


def test_process_synthesizes_sections_when_gemini_returns_flats_only():
    # No usable skills_sections -> sections built from the flat arrays so the
    # output is always classified (no unclassified skill dumps)
    raw = json.dumps({
        "technical_skills": ["Python", "Docker"],
        "core_skills": ["Communication"],
    })
    data = _process_extraction(raw)
    assert data["skills"]["sections"] == [
        {"section_title": "Technical Skills", "items": ["Python", "Docker"]},
        {"section_title": "Soft Skills", "items": ["Communication"]},
    ]


# ---------------------------------------------------------------------------
# Model chain + error matrix (V2 parity)
# ---------------------------------------------------------------------------

def test_model_chain_prefers_configured_order(monkeypatch):
    monkeypatch.setattr(gateway, "_list_supported_generate_models",
                        lambda key: ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-9.9-x"])
    chain = gateway._resolve_model_chain("key")
    assert chain == ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-2.5-flash", "gemini-9.9-x"]


def test_call_gemini_skips_model_returning_empty_text(monkeypatch):
    """A model that answers with a candidate but NO text (safety block,
    non-text part) must be skipped - the next model in the chain is tried,
    never a silent empty-string success (fake-100% root cause)."""
    responses = [
        # First model: 200 but parts without text (degenerate candidate)
        {"candidates": [{"finishReason": "SAFETY",
                         "content": {"parts": [{"inlineData": {"mime_type": "x", "data": "y"}}]}}]},
        # Second model: proper text
        {"candidates": [{"finishReason": "STOP",
                         "content": {"parts": [{"text": '{"job_title": "Nurse"}'}]}}]},
    ]
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, idx):
            self.idx = idx

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps(responses[self.idx]).encode()

    def fake_urlopen(request, timeout=25):
        idx = calls["n"]
        calls["n"] += 1
        return FakeResp(idx)

    monkeypatch.setattr(gateway, "_list_supported_generate_models", lambda key: [])
    monkeypatch.setattr(gateway.urllib.request, "urlopen", fake_urlopen)

    text = _call_gemini("prompt", api_key="key", json_mode=True, max_retries=1)
    assert calls["n"] == 2                       # first model skipped, second used
    assert json.loads(text)["job_title"] == "Nurse"


def test_call_gemini_raises_when_all_models_return_empty_text(monkeypatch):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"candidates": [{"finishReason": "SAFETY",
                                               "content": {"parts": []}}]}).encode()

    monkeypatch.setattr(gateway, "_list_supported_generate_models", lambda key: [])
    monkeypatch.setattr(gateway.urllib.request, "urlopen", lambda req, timeout=25: FakeResp())

    with pytest.raises(GatewayError, match="no usable text"):
        _call_gemini("prompt", api_key="key", json_mode=True, max_retries=1)


def test_model_chain_falls_back_when_listing_fails(monkeypatch):
    monkeypatch.setattr(gateway, "_list_supported_generate_models", lambda key: [])
    assert gateway._resolve_model_chain("key") == gateway.MODEL_FALLBACK_CHAIN


def test_missing_key_raises_clean_error():
    with pytest.raises(GatewayError, match="GEMINI_API_KEY missing"):
        _call_gemini("prompt", api_key="")


def test_extract_requires_enough_text():
    with pytest.raises(GatewayError, match="enough text"):
        gateway.extract_rich_profile_from_text("short", "key")


def test_extract_happy_path_with_mocked_call(monkeypatch):
    captured = {}

    def fake_call(prompt, api_key, json_mode=False, max_retries=2):
        captured["prompt"] = prompt
        captured["json_mode"] = json_mode
        return _canned_response()

    monkeypatch.setattr(gateway, "_call_gemini", fake_call)
    data = gateway.extract_rich_profile_from_text("x" * 200, "key")
    assert data["skills"]["technical"] == ["Python", "Docker"]
    assert "LITERALLY present in the CV text" in captured["prompt"]  # V2 prompt verbatim
    assert captured["json_mode"] is True

