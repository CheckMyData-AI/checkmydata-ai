"""add times_exposed to agent_learnings (C5)

C5, v1.13.0 — split "exposure" (read) from "application" (citation) on
``AgentLearning``. Adds ``times_exposed`` (default 0). The read path
(``get_agent_learnings`` tool) increments this counter; ``times_applied``
remains incremented only when the LLM provably uses a learning (validation
pass). This restores the decay-score signal that was corrupted by every
read inflating ``times_applied``.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-05-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_learnings",
        sa.Column(
            "times_exposed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_learnings", "times_exposed")
