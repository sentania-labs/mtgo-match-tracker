"""Stats endpoints — matchup matrix, play/draw, mulligan, trends.

All stats are scoped by authenticated user. Implementations come after
the data-ingestion endpoints are wired up and we have real rows to
aggregate over.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/matchup-matrix")
async def matchup_matrix(
    format: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    raise NotImplementedError


@router.get("/play-draw")
async def play_draw_split(
    format: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    raise NotImplementedError


@router.get("/mulligans")
async def mulligan_analysis(
    format: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    raise NotImplementedError


@router.get("/trends")
async def trends(
    format: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    raise NotImplementedError


@router.get("/key-cards")
async def key_card_winrates(
    card: str,
    user: User = Depends(get_current_user),
) -> dict:
    raise NotImplementedError
