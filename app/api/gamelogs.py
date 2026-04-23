"""Raw game-log archive ingest (Phase A).

Accepts MTGO .dat / .log file bytes verbatim and stores them on disk
under GAMELOG_ARCHIVE_ROOT, keyed by sha256. The server never parses
these bytes; parsing is Phase 2.5 and happens against already-archived
files.

Idempotency: sha256 unique constraint on game_log_archive. A second
upload of the same bytes returns 200 with the existing row's upload_id
rather than writing a duplicate file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agent
from app.db import get_session
from app.models import AgentRegistration, GameLogArchive, User
from app.schemas import GameLogUploadMetadata, GameLogUploadResponse

router = APIRouter(prefix="/agent/gamelogs", tags=["agent"])

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_ROOT = Path("/data/manalog/gamelogs")
_EXT_BY_TYPE = {"dat": ".dat", "log": ".log"}


def _archive_root() -> Path:
    return Path(os.environ.get("GAMELOG_ARCHIVE_ROOT") or str(DEFAULT_ARCHIVE_ROOT))


def _build_stored_path(
    root: Path, username: str, captured_at: datetime, sha256: str, file_type: str
) -> tuple[Path, str]:
    """Return (absolute_path, relative_path) under ``root``."""
    ext = _EXT_BY_TYPE.get(file_type, "")
    ym = captured_at.astimezone(timezone.utc).strftime("%Y-%m")
    relative = Path(username) / ym / f"{sha256}{ext}"
    return root / relative, str(relative)


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    # NamedTemporaryFile on the same dir so os.replace is atomic.
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@router.post(
    "/upload",
    response_model=GameLogUploadResponse,
)
async def upload_gamelog(
    response: Response,
    file: UploadFile,
    metadata: str = Form(...),
    agent: AgentRegistration = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> GameLogUploadResponse:
    try:
        meta_dict = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metadata must be valid JSON: {exc}",
        )

    try:
        meta = GameLogUploadMetadata.model_validate(meta_dict)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.errors(),
        )

    body = await file.read()

    if len(body) != meta.size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"size mismatch: metadata={meta.size} body={len(body)}",
        )

    computed = hashlib.sha256(body).hexdigest()
    if computed != meta.sha256:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sha256 mismatch between metadata and body",
        )

    # Idempotency: return the existing row if we already hold this sha.
    existing = await session.execute(
        select(GameLogArchive).where(GameLogArchive.sha256 == meta.sha256)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        agent.last_seen = datetime.now(timezone.utc)
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return GameLogUploadResponse(
            upload_id=row.id,
            sha256=row.sha256,
            stored_path=row.stored_path,
            created=False,
        )

    # Resolve optional device attribution. Old agents omit agent_id; new
    # agents include their registration UUID so the archive row can be
    # attributed to a specific device. Silently ignore unknown/revoked
    # values — attribution is best-effort, not a gate.
    attributed_agent_id: uuid.UUID | None = None
    if meta.agent_id is not None:
        result = await session.execute(
            select(AgentRegistration).where(
                AgentRegistration.user_id == agent.user_id,
                AgentRegistration.agent_id == meta.agent_id,
                AgentRegistration.revoked_at.is_(None),
            )
        )
        matched = result.scalar_one_or_none()
        if matched is not None:
            attributed_agent_id = matched.id

    user = await session.get(User, agent.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="agent user missing",
        )

    root = _archive_root()
    absolute, relative = _build_stored_path(
        root,
        username=user.username,
        captured_at=meta.captured_at,
        sha256=meta.sha256,
        file_type=meta.file_type,
    )

    try:
        _atomic_write(absolute, body)
    except OSError as exc:
        logger.exception("gamelog write failed for sha %s", meta.sha256)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to store file: {exc}",
        )

    archive = GameLogArchive(
        uploaded_by_user_id=agent.user_id,
        captured_at=meta.captured_at,
        file_type=meta.file_type,
        original_name=meta.original_name,
        size_bytes=meta.size,
        sha256=meta.sha256,
        stored_path=relative,
        agent_registration_id=attributed_agent_id,
    )
    session.add(archive)
    agent.last_seen = datetime.now(timezone.utc)
    try:
        await session.commit()
    except IntegrityError:
        # Another request won the race and already inserted this sha256.
        # The file on disk is keyed by sha256 and is identical content, so
        # we leave it in place (the winner's row references the same path)
        # and return the existing row idempotently.
        await session.rollback()
        logger.info(
            "Concurrent upload of sha %s lost unique-constraint race; returning existing row",
            meta.sha256,
        )
        existing = await session.execute(
            select(GameLogArchive).where(GameLogArchive.sha256 == meta.sha256)
        )
        row = existing.scalar_one_or_none()
        if row is None:
            # Constraint fired but no row visible — should not happen; surface it.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="integrity error with no existing row",
            )
        agent.last_seen = datetime.now(timezone.utc)
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return GameLogUploadResponse(
            upload_id=row.id,
            sha256=row.sha256,
            stored_path=row.stored_path,
            created=False,
        )
    except Exception:
        # Non-integrity commit failure: the file we just wrote is an orphan
        # (no row references it, and the sha is unique to this attempt).
        logger.exception("DB insert failed for gamelog %s; removing file", meta.sha256)
        try:
            absolute.unlink()
        except OSError:
            pass
        raise
    await session.refresh(archive)

    response.status_code = status.HTTP_201_CREATED
    return GameLogUploadResponse(
        upload_id=archive.id,
        sha256=archive.sha256,
        stored_path=archive.stored_path,
        created=True,
    )
