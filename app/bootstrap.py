"""Startup bootstrap — seed initial users if the DB is empty.

Reads ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL and
TEST_USERNAME / TEST_PASSWORD / TEST_EMAIL from env. Does nothing if
the users table already has rows. Each user is independently guarded
by whether its env vars are present — missing ones are a warning, not
an error.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import hash_password


logger = logging.getLogger(__name__)


async def bootstrap_users(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(User))
    if count:
        return 0

    created = 0

    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@localhost")

    if admin_username and admin_password:
        session.add(
            User(
                username=admin_username,
                email=admin_email,
                hashed_password=hash_password(admin_password),
                is_active=True,
            )
        )
        created += 1
    else:
        logger.warning(
            "users table empty and ADMIN_USERNAME/ADMIN_PASSWORD not set; "
            "skipping admin user seed"
        )

    test_username = os.environ.get("TEST_USERNAME")
    test_password = os.environ.get("TEST_PASSWORD")
    test_email = os.environ.get("TEST_EMAIL", "test@localhost")

    if test_username and test_password:
        session.add(
            User(
                username=test_username,
                email=test_email,
                hashed_password=hash_password(test_password),
                is_active=True,
            )
        )
        created += 1
    else:
        logger.warning(
            "users table empty and TEST_USERNAME/TEST_PASSWORD not set; "
            "skipping test user seed"
        )

    if created == 0:
        logger.warning(
            "no users seeded; agent registration will 401 until a user exists"
        )
        return 0

    await session.commit()
    if admin_username and admin_password:
        logger.info("Created initial admin user %r", admin_username)
    if test_username and test_password:
        logger.info("Created test user %r", test_username)
    return created
