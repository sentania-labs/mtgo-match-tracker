"""Startup bootstrap — seed an initial admin user if the DB is empty.

Reads ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL from env. Does
nothing if the users table already has rows, or if the env vars aren't
set. Missing env vars are a warning, not an error — that's the
expected state once the first user is created and the env is scrubbed.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import hash_password


logger = logging.getLogger(__name__)


async def bootstrap_admin_user(session: AsyncSession) -> bool:
    count = await session.scalar(select(func.count()).select_from(User))
    if count:
        return False

    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    email = os.environ.get("ADMIN_EMAIL", "admin@localhost")

    if not username or not password:
        logger.warning(
            "users table empty and ADMIN_USERNAME/ADMIN_PASSWORD not set; "
            "agent registration will 401 until a user exists"
        )
        return False

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    session.add(user)
    await session.commit()
    logger.info("Created initial admin user %r", username)
    return True
