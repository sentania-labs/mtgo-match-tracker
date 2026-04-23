"""Admin endpoints for managing agent registrations.

Admin auth is HTTP Basic against the users table, gated by the
``MANALOG_ADMIN_USERNAME`` env var — only that user is treated as
admin. If the env var is unset, every request is 403 (no admin).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AgentRegistration, User
from app.security import verify_password

router = APIRouter(prefix="/admin", tags=["admin"])

_basic = HTTPBasic(auto_error=False)


async def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    session: AsyncSession = Depends(get_session),
) -> User:
    admin_username = os.environ.get("MANALOG_ADMIN_USERNAME")
    if not admin_username or credentials is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    if credentials.username != admin_username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    result = await session.execute(
        select(User).where(User.username == credentials.username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    return user


@router.get("/agents")
async def list_agents(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(select(AgentRegistration))
    rows = result.scalars().all()
    return [
        {
            "id": str(row.id),
            "agent_id": str(row.agent_id),
            "machine_name": row.machine_name,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }
        for row in rows
    ]


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_agent(
    agent_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(
        select(AgentRegistration).where(AgentRegistration.agent_id == agent_id)
    )
    registration = result.scalar_one_or_none()
    if registration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    if registration.revoked_at is None:
        registration.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
