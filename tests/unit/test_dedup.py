"""Dedup constraint: (user_id, mtgo_match_id) must be unique per user."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Match


async def test_mtgo_match_id_unique_per_user(async_session) -> None:
    user_id = uuid4()
    mtgo_id = "MTGO-123456"

    async_session.add(
        Match(
            user_id=user_id,
            mtgo_match_id=mtgo_id,
            format="modern",
            match_type="league",
            result="win",
        )
    )
    await async_session.commit()

    async_session.add(
        Match(
            user_id=user_id,
            mtgo_match_id=mtgo_id,
            format="modern",
            match_type="league",
            result="loss",
        )
    )
    with pytest.raises(IntegrityError):
        await async_session.commit()
