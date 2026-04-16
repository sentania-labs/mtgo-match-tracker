from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models import User
from app.schemas import DecklistCreate, DecklistRead

router = APIRouter(prefix="/decklists", tags=["decklists"])


@router.get("", response_model=list[DecklistRead])
async def list_decklists(user: User = Depends(get_current_user)) -> list[DecklistRead]:
    raise NotImplementedError


@router.post("", response_model=DecklistRead, status_code=status.HTTP_201_CREATED)
async def create_decklist(
    payload: DecklistCreate,
    user: User = Depends(get_current_user),
) -> DecklistRead:
    raise NotImplementedError


@router.get("/{decklist_id}", response_model=DecklistRead)
async def get_decklist(
    decklist_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> DecklistRead:
    raise NotImplementedError
