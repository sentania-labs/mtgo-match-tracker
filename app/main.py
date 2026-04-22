"""FastAPI entry point for Manalog — MTGO Match Tracker."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import (
    agent,
    archetypes,
    decklists,
    drafts,
    gamelogs,
    games,
    matches,
    stats,
)
from app.bootstrap import bootstrap_users
from app.db import SessionLocal, engine

logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as session:
        await bootstrap_users(session)
    yield
    await engine.dispose()


app = FastAPI(
    title="Manalog — MTGO Match Tracker",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz", tags=["health"])
async def healthz(response: Response) -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("healthz DB check failed: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "db": "unreachable"}
    return {"status": "ok", "db": "ok"}


for router in (
    agent.router,
    gamelogs.router,
    matches.router,
    games.router,
    decklists.router,
    archetypes.router,
    drafts.router,
    stats.router,
):
    app.include_router(router, prefix=API_V1_PREFIX)


# CORS: FastAPI middleware is only attached when explicit origins are
# configured via env. Default is no CORS (browser same-origin only).
_cors_origins = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
