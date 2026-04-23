from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class GameLogUploadMetadata(BaseModel):
    """Metadata side of the multipart upload posted to /agent/gamelogs/upload."""

    original_name: str = Field(min_length=1, max_length=512)
    file_type: Literal["dat", "log"]
    captured_at: datetime
    size: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    agent_id: UUID | None = None

    @field_validator("sha256")
    @classmethod
    def _hex_sha256(cls, value: str) -> str:
        lowered = value.lower()
        if not all(c in "0123456789abcdef" for c in lowered):
            raise ValueError("sha256 must be 64 hex characters")
        return lowered


class GameLogUploadResponse(BaseModel):
    upload_id: int
    sha256: str
    stored_path: str
    created: bool
