from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.schemas import ArchetypeCreate, ArchetypeRead

# Archetypes are shared reference data — not user-scoped.
router = APIRouter(prefix="/archetypes", tags=["archetypes"])


@router.get("", response_model=list[ArchetypeRead])
async def list_archetypes(format: str | None = None) -> list[ArchetypeRead]:
    raise NotImplementedError


@router.post("", response_model=ArchetypeRead, status_code=status.HTTP_201_CREATED)
async def create_archetype(payload: ArchetypeCreate) -> ArchetypeRead:
    raise NotImplementedError


@router.get("/{archetype_id}", response_model=ArchetypeRead)
async def get_archetype(archetype_id: uuid.UUID) -> ArchetypeRead:
    raise NotImplementedError
