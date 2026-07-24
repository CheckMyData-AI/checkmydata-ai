"""add learning_votes table

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-24

AQ-7: per-user vote dedup for learning confirm/contradict. One active vote
per (learning_id, user_id) so a single user cannot pump a learning's
confidence to 1.0 / ★CRITICAL with repeated clicks, nor deactivate someone
else's learning with two contradict clicks. A repeated same-sign vote is a
no-op; a sign change reverses the previous effect
(``AgentLearningService.vote_learning``). Additive-only — safe on Postgres
(prod) and SQLite (dev) alike.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "learning_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "learning_id",
            sa.String(36),
            sa.ForeignKey("agent_learnings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("learning_id", "user_id", name="uq_learning_vote_user"),
    )
    op.create_index("ix_learning_votes_learning_id", "learning_votes", ["learning_id"])
    op.create_index("ix_learning_votes_user_id", "learning_votes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_votes_user_id", table_name="learning_votes")
    op.drop_index("ix_learning_votes_learning_id", table_name="learning_votes")
    op.drop_table("learning_votes")
