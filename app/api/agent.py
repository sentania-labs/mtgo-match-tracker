"""Agent-facing endpoints: registration, heartbeat, match upload.

Registration and heartbeat are real (DB-backed). Match upload is still
a stub — it acknowledges the payload and returns 202 without persisting.
Real ingest is post-MVP.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.db import get_session
from app.models import AgentRegistration, User
from app.schemas import (
    AgentMatchUpload,
    AgentRegisterRequest,
    AgentRegisterResponse,
)
from app.security import generate_token, hash_token, verify_password

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/register",
    response_model=AgentRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_agent(
    payload: AgentRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentRegisterResponse:
    result = await session.execute(
        select(User).where(User.username == payload.username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    token = generate_token()
    registration = AgentRegistration(
        user_id=user.id,
        machine_name=payload.machine_name,
        platform=payload.platform,
        api_token_hash=hash_token(token),
    )
    session.add(registration)
    await session.commit()
    await session.refresh(registration)

    return AgentRegisterResponse(agent_id=registration.agent_id, api_token=token)


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    agent: AgentRegistration = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> Response:
    agent.last_seen = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_match(
    payload: AgentMatchUpload,
    agent: AgentRegistration = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    agent.last_seen = datetime.now(timezone.utc)
    await session.commit()
    return {
        "status": "queued",
        "mtgo_match_id": payload.match.mtgo_match_id,
    }
