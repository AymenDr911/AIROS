"""AIROS V3 - /api/me endpoint tests (Slice 5): verified identity + own row."""

from __future__ import annotations

from tests.conftest import mint_token


def test_me_returns_claims_and_account(client, rsa_material, monkeypatch):
    import services.api.routers.me as me_router

    account_row = {
        "id": "acc-1",
        "email": "tester@airos.dev",
        "auth0_sub": "auth0|testuser",
        "verified": True,
        "created_at": "2026-09-01T00:00:00",
        "updated_at": "2026-09-01T00:00:00",
        "source_key": None,
    }
    captured = {}

    def fake_fetch_account(token: str, sub: str):
        captured["token"] = token
        captured["sub"] = sub
        return account_row

    monkeypatch.setattr(me_router, "fetch_account", fake_fetch_account)

    token = mint_token(rsa_material[0])
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == "auth0|testuser"
    assert body["email"] == "tester@airos.dev"
    assert body["role"] == "authenticated"
    assert body["account"] == account_row
    assert body["provision_hint"] is None
    # DEC-014: the API forwards the caller's OWN token, no substitution.
    assert captured["token"] == token
    assert captured["sub"] == "auth0|testuser"


def test_me_without_account_row_gives_provision_hint(client, rsa_material, monkeypatch):
    import services.api.routers.me as me_router

    monkeypatch.setattr(me_router, "fetch_account", lambda token, sub: None)

    token = mint_token(rsa_material[0])
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["account"] is None
    assert "sync_my_account" in (body["provision_hint"] or "")


def test_me_upstream_error_maps_to_502(client, rsa_material, monkeypatch):
    import services.api.routers.me as me_router
    from fastapi import HTTPException

    def boom(token: str, sub: str):
        raise HTTPException(status_code=502, detail="upstream PostgREST error: HTTP 500")

    monkeypatch.setattr(me_router, "fetch_account", boom)

    token = mint_token(rsa_material[0])
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 502
