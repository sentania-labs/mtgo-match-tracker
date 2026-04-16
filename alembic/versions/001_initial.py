"""initial schema — all 9 tables

Revision ID: 001_initial
Revises:
Create Date: 2026-04-16

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "agent_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("machine_name", sa.String(128), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("api_token_hash", sa.String(255), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_registrations_user_id", "agent_registrations", ["user_id"])

    op.create_table(
        "archetypes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("aliases", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("colors", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("key_cards", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "format", name="uq_archetype_name_format"),
    )
    op.create_index("ix_archetypes_name", "archetypes", ["name"])
    op.create_index("ix_archetypes_format", "archetypes", ["format"])

    op.create_table(
        "decklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column(
            "archetype_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("archetypes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("maindeck", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("sideboard", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_decklists_user_id", "decklists", ["user_id"])

    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mtgo_match_id", sa.String(64), nullable=True),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("match_type", sa.String(32), nullable=False),
        sa.Column("event_name", sa.String(255), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opponent_name", sa.String(128), nullable=True),
        sa.Column(
            "my_archetype_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("archetypes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "opponent_archetype_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("archetypes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("my_archetype_name", sa.String(128), nullable=True),
        sa.Column("opponent_archetype_name", sa.String(128), nullable=True),
        sa.Column(
            "decklist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("decklists.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("my_wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opponent_wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "mtgo_match_id", name="uq_match_user_mtgoid"),
    )
    op.create_index("ix_matches_user_id", "matches", ["user_id"])

    op.create_table(
        "games",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("game_number", sa.Integer, nullable=False),
        sa.Column("on_play", sa.Boolean, nullable=True),
        sa.Column("my_mulligans", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opponent_mulligans", sa.Integer, nullable=False, server_default="0"),
        sa.Column("turn_count", sa.Integer, nullable=True),
        sa.Column("winner", sa.String(16), nullable=False),
    )
    op.create_index("ix_games_match_id", "games", ["match_id"])

    op.create_table(
        "plays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "game_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn", sa.Integer, nullable=False),
        sa.Column("caster", sa.String(16), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("card_name", sa.String(128), nullable=False),
        sa.Column("targets", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_plays_game_id", "plays", ["game_id"])

    op.create_table(
        "drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_code", sa.String(16), nullable=False),
        sa.Column("draft_type", sa.String(32), nullable=False),
        sa.Column("event_name", sa.String(255), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_drafts_user_id", "drafts", ["user_id"])

    op.create_table(
        "picks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pack", sa.Integer, nullable=False),
        sa.Column("pick", sa.Integer, nullable=False),
        sa.Column("card_name", sa.String(128), nullable=False),
        sa.Column("alternatives", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.create_index("ix_picks_draft_id", "picks", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_picks_draft_id", table_name="picks")
    op.drop_table("picks")
    op.drop_index("ix_drafts_user_id", table_name="drafts")
    op.drop_table("drafts")
    op.drop_index("ix_plays_game_id", table_name="plays")
    op.drop_table("plays")
    op.drop_index("ix_games_match_id", table_name="games")
    op.drop_table("games")
    op.drop_index("ix_matches_user_id", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_decklists_user_id", table_name="decklists")
    op.drop_table("decklists")
    op.drop_index("ix_archetypes_format", table_name="archetypes")
    op.drop_index("ix_archetypes_name", table_name="archetypes")
    op.drop_table("archetypes")
    op.drop_index("ix_agent_registrations_user_id", table_name="agent_registrations")
    op.drop_table("agent_registrations")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
