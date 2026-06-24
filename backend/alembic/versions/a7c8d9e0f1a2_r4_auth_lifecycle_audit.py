"""R4: email verification columns + durable audit_logs table

Revision ID: a7c8d9e0f1a2
Revises: f4a5b6c7d8e9
Create Date: 2026-06-25

"""

import sqlalchemy as sa
from alembic import op

revision = "a7c8d9e0f1a2"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("email_verify_token", sa.String(length=64), nullable=True))

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_column("users", "email_verify_token")
    op.drop_column("users", "email_verified")
