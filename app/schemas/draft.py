from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PickBase(BaseModel):
    pack: int
    pick: int
    card_name: str = Field(min_length=1, max_length=128)
    alternatives: list[str] = Field(default_factory=list)


class PickCreate(PickBase):
    pass


class PickRead(PickBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    draft_id: uuid.UUID


class DraftBase(BaseModel):
    set_code: str = Field(min_length=1, max_length=16)
    draft_type: str = Field(min_length=1, max_length=32)
    event_name: str | None = None
    event_date: datetime | None = None
    wins: int = 0
    losses: int = 0
    notes: str | None = None


class DraftCreate(DraftBase):
    picks: list[PickCreate] = Field(default_factory=list)


class DraftRead(DraftBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    picks: list[PickRead] = Field(default_factory=list)
