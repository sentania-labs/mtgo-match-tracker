"""Healthz smoke — the compose smoke test depends on this."""
from __future__ import annotations


async def test_healthz(client) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
