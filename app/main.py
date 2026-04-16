"""FastAPI entry point for Tamiyo — MTGO Match Tracker."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import (
    agent,
    archetypes,
    decklists,
    drafts,
    games,
    matches,
    stats,
)
from app.db import engine

API_V1_PREFIX = "/api/v1"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Tamiyo — MTGO Match Tracker",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz", tags=["health"])
async def healthz() -> dict:
    return {"status": "ok"}


for router in (
    agent.router,
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
