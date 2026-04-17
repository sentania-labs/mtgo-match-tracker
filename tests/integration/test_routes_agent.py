"""Behavior coverage for /api/v1/agent/* — register, heartbeat, upload.

Covers the auth paths (valid creds, bad password, missing token, revoked
token) because those are the MVP boundary — everything agents rely on
passes through these endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import AgentRegistration


async def test_register_valid_credentials(client) -> None:
    resp = await client.post(
        "/api/v1/agent/register",
        json={
            "username": "testuser",
            "password": "hunter2",
            "machine_name": "test-pc",
            "platform": "linux",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    uuid.UUID(body["agent_id"])
    assert len(body["api_token"]) > 20


async def test_register_wrong_password(client) -> None:
    resp = await client.post(
        "/api/v1/agent/register",
        json={
            "username": "testuser",
            "password": "wrong",
            "machine_name": "test-pc",
            "platform": "linux",
        },
    )
    assert resp.status_code == 401


async def test_register_unknown_user(client) -> None:
    resp = await client.post(
        "/api/v1/agent/register",
        json={
            "username": "nobody",
            "password": "whatever",
            "machine_name": "test-pc",
            "platform": "linux",
        },
    )
    assert resp.status_code == 401


async def test_heartbeat_bumps_last_seen(client, registered_agent, async_session) -> None:
    resp = await client.post("/api/v1/agent/heartbeat", headers=registered_agent["auth_header"])
    assert resp.status_code == 204
    # Verify last_seen moved off NULL
    result = await async_session.execute(
        select(AgentRegistration).where(
            AgentRegistration.agent_id == uuid.UUID(registered_agent["agent_id"])
        )
    )
    row = result.scalar_one()
    assert row.last_seen is not None
    # last_seen should be roughly now
    now = datetime.now(timezone.utc)
    delta = (now - row.last_seen.replace(tzinfo=timezone.utc)).total_seconds()
    assert abs(delta) < 5


async def test_heartbeat_missing_token(client) -> None:
    resp = await client.post("/api/v1/agent/heartbeat")
    assert resp.status_code == 401


async def test_heartbeat_bad_token(client) -> None:
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_heartbeat_malformed_header(client) -> None:
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": "just-a-token-no-scheme"},
    )
    assert resp.status_code == 401


async def test_heartbeat_revoked_agent(client, registered_agent, async_session) -> None:
    result = await async_session.execute(
        select(AgentRegistration).where(
            AgentRegistration.agent_id == uuid.UUID(registered_agent["agent_id"])
        )
    )
    row = result.scalar_one()
    row.revoked_at = datetime.now(timezone.utc)
    await async_session.commit()

    resp = await client.post("/api/v1/agent/heartbeat", headers=registered_agent["auth_header"])
    assert resp.status_code == 401


async def test_upload_requires_auth(client) -> None:
    payload = {
        "agent_id": str(uuid.uuid4()),
        "match": {
            "mtgo_match_id": "MTGO-1",
            "format": "modern",
            "match_type": "league",
            "result": "win",
            "my_wins": 2,
            "opponent_wins": 1,
        },
    }
    resp = await client.post("/api/v1/agent/upload", json=payload)
    assert resp.status_code == 401


async def test_upload_with_valid_token(client, registered_agent) -> None:
    payload = {
        "agent_id": registered_agent["agent_id"],
        "match": {
            "mtgo_match_id": "MTGO-HB-1",
            "format": "modern",
            "match_type": "league",
            "result": "win",
            "my_wins": 2,
            "opponent_wins": 1,
        },
    }
    resp = await client.post(
        "/api/v1/agent/upload",
        json=payload,
        headers=registered_agent["auth_header"],
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["mtgo_match_id"] == "MTGO-HB-1"
