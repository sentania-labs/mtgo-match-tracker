from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ArchetypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    format: str = Field(min_length=1, max_length=32)
    aliases: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    key_cards: list[str] = Field(default_factory=list)
    source: str | None = None


class ArchetypeCreate(ArchetypeBase):
    pass


class ArchetypeRead(ArchetypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    updated_at: datetime
