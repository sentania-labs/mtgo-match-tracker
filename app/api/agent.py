"""Agent-facing endpoints: registration + match upload.

Bearer-token auth will be added in Phase 1.5. The upload endpoint stub
currently uses the dev user; real deployments will resolve the user from
the agent's bearer token.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models import User
from app.schemas import (
    AgentMatchUpload,
    AgentRegisterRequest,
    AgentRegisterResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/register", response_model=AgentRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(payload: AgentRegisterRequest) -> AgentRegisterResponse:
    """Register a new agent instance for this user.

    TODO(phase-1.5): verify username/password, create AgentRegistration row,
    hash + store the api_token, return the plaintext token (shown once).
    """
    raise NotImplementedError("Agent registration pending Phase 1.5 auth")


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_match(
    payload: AgentMatchUpload,
    user: User = Depends(get_current_user),
) -> dict:
    """Accept a match result from an agent.

    TODO(phase-1.5): validate bearer token → agent, upsert match row
    keyed on (user_id, mtgo_match_id), create games + plays.
    """
    raise NotImplementedError("Agent upload pending Phase 1.5 ingest")
