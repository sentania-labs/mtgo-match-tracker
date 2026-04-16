from __future__ import annotations

VALID_STUB_STATUSES = {200, 201, 422, 500, 501}


async def test_list_drafts_reachable(client) -> None:
    resp = await client.get("/api/v1/drafts")
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES
