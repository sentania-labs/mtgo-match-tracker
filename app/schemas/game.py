from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


GameWinner = Literal["me", "opponent", "draw"]
Caster = Literal["me", "opponent"]


class PlayBase(BaseModel):
    turn: int
    caster: Caster
    action_type: str = Field(min_length=1, max_length=32)
    card_name: str = Field(min_length=1, max_length=128)
    targets: list[str] | None = None


class PlayCreate(PlayBase):
    pass


class PlayRead(PlayBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    game_id: uuid.UUID


class GameBase(BaseModel):
    game_number: int
    on_play: bool | None = None
    my_mulligans: int = 0
    opponent_mulligans: int = 0
    turn_count: int | None = None
    winner: GameWinner


class GameCreate(GameBase):
    plays: list[PlayCreate] = Field(default_factory=list)


class GameRead(GameBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_id: uuid.UUID
    plays: list[PlayRead] = Field(default_factory=list)
