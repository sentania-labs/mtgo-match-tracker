from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models import User
from app.schemas import GameCreate, GameRead

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=list[GameRead])
async def list_games(
    match_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
) -> list[GameRead]:
    raise NotImplementedError


@router.post("", response_model=GameRead, status_code=status.HTTP_201_CREATED)
async def create_game(
    match_id: uuid.UUID,
    payload: GameCreate,
    user: User = Depends(get_current_user),
) -> GameRead:
    raise NotImplementedError


@router.get("/{game_id}", response_model=GameRead)
async def get_game(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> GameRead:
    raise NotImplementedError
