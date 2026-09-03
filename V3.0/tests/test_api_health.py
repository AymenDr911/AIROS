"""AIROS V3 - /api/health (Slice 5): liveness + config surfacing, no auth."""

from __future__ import annotations


def test_health_ok_no_auth(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "airos-api"
    assert body["env"] == "test"
    assert body["config"] == "ok"


def test_health_reports_incomplete_config(api_env, monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN")
    from fastapi.testclient import TestClient

    from services.api.config import get_settings
    from services.api.main import create_app

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as fresh:
            resp = fresh.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["config"] == "incomplete"
    finally:
        get_settings.cache_clear()


def test_cors_allows_configured_origin(client):
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
