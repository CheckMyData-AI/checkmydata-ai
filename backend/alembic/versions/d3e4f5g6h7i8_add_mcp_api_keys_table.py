"""add mcp_api_keys table

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-06-20
"""

import sqlalchemy as sa

from alembic import op

revision = "d3e4f5g6h7i8"
down_revision = "c2d3e4f5g6h7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_mcp_api_keys_token_hash"),
    )
    op.create_index("ix_mcp_api_keys_user_id", "mcp_api_keys", ["user_id"])
    # DATA-07: no second index on `token_hash`. The model renders
    # `unique=True, index=True` as ONE unique index called
    # `ix_mcp_api_keys_token_hash`; this migration used to declare a
    # UniqueConstraint (which brings its own implicit index) AND a plain index under
    # that same name — so production carried two btree indexes on one 64-char column
    # and the object named `ix_mcp_api_keys_token_hash` meant different things in the
    # two schemas. A follow-up revision drops the redundant object where it exists.


def downgrade() -> None:
    op.drop_index("ix_mcp_api_keys_user_id", table_name="mcp_api_keys")
    op.drop_table("mcp_api_keys")
