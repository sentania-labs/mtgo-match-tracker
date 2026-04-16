from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DecklistBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    format: str = Field(min_length=1, max_length=32)
    archetype_id: uuid.UUID | None = None
    # Maindeck / sideboard stored as {card_name: quantity} maps.
    maindeck: dict[str, int] = Field(default_factory=dict)
    sideboard: dict[str, int] = Field(default_factory=dict)


class DecklistCreate(DecklistBase):
    pass


class DecklistRead(DecklistBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    retired_at: datetime | None
