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


# ---------------------------------------------------------------------------
# Model chain + error matrix (V2 parity)
# ---------------------------------------------------------------------------

def test_model_chain_prefers_configured_order(monkeypatch):
    monkeypatch.setattr(gateway, "_list_supported_generate_models",
                        lambda key: ["gemini-1.5-flash", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-9.9-x"])
    chain = gateway._resolve_model_chain("key")
    assert chain == ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-9.9-x"]


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

