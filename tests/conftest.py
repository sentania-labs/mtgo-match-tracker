"""Shared pytest fixtures.

DATABASE_URL is forced to in-memory SQLite before any app import so the
FastAPI app binds to an ephemeral engine, not PostgreSQL. The PostgreSQL-
only types in `app.models.models` (UUID, JSONB) are down-compiled to
SQLite equivalents via SQLAlchemy compiler hooks.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


from app.api.deps import get_current_user  # noqa: E402 — must follow env setup
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.security import hash_password  # noqa: E402


TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USERNAME = "testuser"
TEST_PASSWORD = "hunter2"  # noqa: S105 — test fixture


def _test_user() -> User:
    from datetime import datetime, timezone

    return User(
        id=TEST_USER_ID,
        username=TEST_USERNAME,
        email="test@localhost",
        hashed_password="!",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(
            User(
                id=TEST_USER_ID,
                username=TEST_USERNAME,
                email="test@localhost",
                hashed_password=hash_password(TEST_PASSWORD),
                is_active=True,
            )
        )
        await session.commit()
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def client(async_engine) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = _test_user
    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_app_engine() -> AsyncIterator[None]:
    """Dispose the module-level app.db engine after the session so
    connection-pool threads don't block Python's exit."""
    yield
    import app.db as _db
    await _db.engine.dispose()


@pytest_asyncio.fixture
async def registered_agent(client) -> dict:
    """Register a fresh agent against the seeded test user; return creds."""
    resp = await client.post(
        "/api/v1/agent/register",
        json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
            "machine_name": "test-pc",
            "platform": "linux",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    return {
        "agent_id": body["agent_id"],
        "api_token": body["api_token"],
        "auth_header": {"Authorization": f"Bearer {body['api_token']}"},
    }
