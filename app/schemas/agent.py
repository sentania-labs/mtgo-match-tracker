from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.match import MatchCreate


class AgentRegisterRequest(BaseModel):
    """Request body for POST /api/v1/agent/register.

    Agent authenticates with username/password once at registration to
    receive a long-lived api_token bound to this machine.
    """
    username: str
    password: str
    machine_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)


class AgentRegisterResponse(BaseModel):
    """Response for a successful registration. api_token is shown once."""
    agent_id: uuid.UUID
    api_token: str


class AgentRegistrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    machine_name: str
    platform: str
    last_seen: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class AgentMatchUpload(BaseModel):
    """Payload posted to /api/v1/agent/upload when an agent observes a match."""
    agent_id: uuid.UUID
    match: MatchCreate
