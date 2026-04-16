"""API dependencies.

Auth middleware is Phase 1.5 — for now `get_current_user` returns a
hardcoded dev User so routes can be built and exercised. Do NOT ship this
to production. The stub is intentionally loud: it does not touch the DB
and returns a synthetic object so anything that tries to persist against
it will fail fast.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import User

DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_user() -> User:
    user = User(
        id=DEV_USER_ID,
        username="dev",
        email="dev@localhost",
        hashed_password="!",  # noqa: S105 — stub, not persisted
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    return user
