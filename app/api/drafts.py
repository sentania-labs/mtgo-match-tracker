from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models import User
from app.schemas import DraftCreate, DraftRead

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftRead])
async def list_drafts(user: User = Depends(get_current_user)) -> list[DraftRead]:
    raise NotImplementedError


@router.post("", response_model=DraftRead, status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: DraftCreate,
    user: User = Depends(get_current_user),
) -> DraftRead:
    raise NotImplementedError


@router.get("/{draft_id}", response_model=DraftRead)
async def get_draft(
    draft_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> DraftRead:
    raise NotImplementedError
