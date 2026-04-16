"""Async SQLAlchemy engine + session factory.

DATABASE_URL is read from the environment (set in docker-compose.yml or .env).
Example: postgresql+asyncpg://mtgo:changeme@db/mtgo_tracker
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://mtgo:changeme@db/mtgo_tracker",
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async DB session."""
    async with SessionLocal() as session:
        yield session
