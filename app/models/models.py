"""SQLAlchemy 2.0 ORM models for the MTGO Match Tracker.

All user-scoped data tables carry a `user_id` FK to `users.id` per
CLAUDE.md hard rule #7. UUID primary keys are used throughout so agents
can generate IDs client-side before server confirmation.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    agents: Mapped[list["AgentRegistration"]] = relationship(back_populates="user")
    matches: Mapped[list["Match"]] = relationship(back_populates="user")
    decklists: Mapped[list["Decklist"]] = relationship(back_populates="user")
    drafts: Mapped[list["Draft"]] = relationship(back_populates="user")


class AgentRegistration(Base):
    """A registered agent instance. A single user may have many (desktop + laptop)."""
    __tablename__ = "agent_registrations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    machine_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    api_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="agents")
    submitted_matches: Mapped[list["Match"]] = relationship(back_populates="submitted_by_agent")


class Archetype(Base):
    """Shared reference data synced from external sources (TopDeck, MTG Top 8, etc.).

    Not user-scoped — archetypes are canonical across the system.
    """
    __tablename__ = "archetypes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    colors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    key_cards: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("name", "format", name="uq_archetype_name_format"),
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: manual/paper entries aren't attributed to any agent.
    submitted_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # MTGO's internal match id, when known. Unique per-user (not globally)
    # so two users' agents posting the same id don't collide.
    mtgo_match_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    format: Mapped[str] = mapped_column(String(32), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)  # league / tournament / paper / casual
    event_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opponent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    my_archetype_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True
    )
    opponent_archetype_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True
    )
    # Free-form overrides for when the lookup table doesn't have a match.
    my_archetype_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    opponent_archetype_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    decklist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decklists.id", ondelete="SET NULL"), nullable=True
    )

    result: Mapped[str] = mapped_column(String(16), nullable=False)  # win / loss / draw
    my_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opponent_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Dedup per user: same user resubmitting the same MTGO match_id is idempotent.
        UniqueConstraint("user_id", "mtgo_match_id", name="uq_match_user_mtgoid"),
    )

    user: Mapped[User] = relationship(back_populates="matches")
    submitted_by_agent: Mapped[AgentRegistration | None] = relationship(back_populates="submitted_matches")
    games: Mapped[list["Game"]] = relationship(back_populates="match", cascade="all, delete-orphan")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[uuid.UUID] = _uuid_pk()
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)
    on_play: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    my_mulligans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opponent_mulligans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner: Mapped[str] = mapped_column(String(16), nullable=False)  # me / opponent / draw

    match: Mapped[Match] = relationship(back_populates="games")
    plays: Mapped[list["Play"]] = relationship(back_populates="game", cascade="all, delete-orphan")


class Play(Base):
    """Turn-by-turn card action within a game."""
    __tablename__ = "plays"

    id: Mapped[uuid.UUID] = _uuid_pk()
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    caster: Mapped[str] = mapped_column(String(16), nullable=False)  # me / opponent
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)  # cast / activate / trigger / etc.
    card_name: Mapped[str] = mapped_column(String(128), nullable=False)
    targets: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    game: Mapped[Game] = relationship(back_populates="plays")


class Decklist(Base):
    __tablename__ = "decklists"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    archetype_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("archetypes.id", ondelete="SET NULL"), nullable=True
    )
    maindeck: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sideboard: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="decklists")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    set_code: Mapped[str] = mapped_column(String(16), nullable=False)
    draft_type: Mapped[str] = mapped_column(String(32), nullable=False)  # league / premier / sealed / etc.
    event_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="drafts")
    picks: Mapped[list["Pick"]] = relationship(back_populates="draft", cascade="all, delete-orphan")


class Pick(Base):
    __tablename__ = "picks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pack: Mapped[int] = mapped_column(Integer, nullable=False)
    pick: Mapped[int] = mapped_column(Integer, nullable=False)
    card_name: Mapped[str] = mapped_column(String(128), nullable=False)
    alternatives: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    draft: Mapped[Draft] = relationship(back_populates="picks")
