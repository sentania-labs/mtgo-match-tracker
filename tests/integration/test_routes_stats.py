from __future__ import annotations

VALID_STUB_STATUSES = {200, 201, 422, 500, 501}


async def test_matchup_matrix_reachable(client) -> None:
    resp = await client.get("/api/v1/stats/matchup-matrix")
    assert resp.status_code != 404
    assert resp.status_code in VALID_STUB_STATUSES
