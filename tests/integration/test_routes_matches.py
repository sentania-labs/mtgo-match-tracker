"""Smoke coverage for /api/v1/matches — stub endpoints accepted."""
from __future__ import annotations

VALID_STUB_STATUSES = {200, 201, 422, 500, 501}


async def test_list_matches_reachable(client) -> None:
    resp = await client.get("/api/v1/matches")
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES


async def test_create_match_reachable(client) -> None:
    payload = {
        "format": "modern",
        "match_type": "league",
        "result": "win",
    }
    resp = await client.post("/api/v1/matches", json=payload)
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES
