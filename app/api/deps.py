"""API dependencies.

`get_current_user` is still a dev stub returning a synthetic User —
browser-facing auth (login/session) is out of MVP scope. Agent-facing
auth IS real: `get_current_agent` resolves the bearer token against
agent_registrations and rejects missing/unknown/revoked tokens.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AgentRegistration, User
from app.security import hash_token

DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_user() -> User:
    user = User(
        id=DEV_USER_ID,
        username="dev",
        email="dev@localhost",
        hashed_password="!",  # noqa: S105 — stub, not persisted
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    return user


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def get_current_agent(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> AgentRegistration:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token_hash = hash_token(token)
    result = await session.execute(
        select(AgentRegistration).where(
            AgentRegistration.api_token_hash == token_hash,
            AgentRegistration.revoked_at.is_(None),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    return agent
