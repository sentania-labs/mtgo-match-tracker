"""agent_registration_id on game_log_archive — device attribution

Revision ID: 003_agent_registration_on_archive
Revises: 002_game_log_archive
Create Date: 2026-04-22

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_agent_registration_on_archive"
down_revision: Union[str, None] = "002_game_log_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "game_log_archive",
        sa.Column(
            "agent_registration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_game_log_archive_agent_registration_id",
        "game_log_archive",
        ["agent_registration_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_log_archive_agent_registration_id",
        table_name="game_log_archive",
    )
    op.drop_column("game_log_archive", "agent_registration_id")
