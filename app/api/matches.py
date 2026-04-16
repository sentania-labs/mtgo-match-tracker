from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models import User
from app.schemas import MatchCreate, MatchRead

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchRead])
async def list_matches(user: User = Depends(get_current_user)) -> list[MatchRead]:
    raise NotImplementedError


@router.post("", response_model=MatchRead, status_code=status.HTTP_201_CREATED)
async def create_match(
    payload: MatchCreate,
    user: User = Depends(get_current_user),
) -> MatchRead:
    raise NotImplementedError


@router.get("/{match_id}", response_model=MatchRead)
async def get_match(
    match_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> MatchRead:
    raise NotImplementedError
