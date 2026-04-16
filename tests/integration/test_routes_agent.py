"""Smoke coverage for /api/v1/agent/* — register + upload."""
from __future__ import annotations

VALID_STUB_STATUSES = {200, 201, 202, 422, 500, 501}


async def test_register_reachable(client) -> None:
    payload = {
        "username": "testuser",
        "password": "hunter2",
        "machine_name": "test-pc",
        "platform": "windows",
    }
    resp = await client.post("/api/v1/agent/register", json=payload)
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES


async def test_upload_reachable(client) -> None:
    payload = {
        "mtgo_match_id": "MTGO-1",
        "format": "modern",
        "result": "win",
    }
    resp = await client.post("/api/v1/agent/upload", json=payload)
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES
