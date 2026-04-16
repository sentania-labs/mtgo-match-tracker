from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MatchResult = Literal["win", "loss", "draw"]
MatchType = Literal["league", "tournament", "paper", "casual", "other"]


class MatchBase(BaseModel):
    format: str = Field(min_length=1, max_length=32)
    match_type: MatchType = "other"
    event_name: str | None = None
    event_date: datetime | None = None
    opponent_name: str | None = None

    my_archetype_id: uuid.UUID | None = None
    opponent_archetype_id: uuid.UUID | None = None
    my_archetype_name: str | None = None
    opponent_archetype_name: str | None = None

    decklist_id: uuid.UUID | None = None

    result: MatchResult
    my_wins: int = 0
    opponent_wins: int = 0

    notes: str | None = None


class MatchCreate(MatchBase):
    # Optional because manual entries won't have an MTGO-assigned id.
    mtgo_match_id: str | None = None


class MatchRead(MatchBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    submitted_by_agent_id: uuid.UUID | None
    mtgo_match_id: str | None
    created_at: datetime
