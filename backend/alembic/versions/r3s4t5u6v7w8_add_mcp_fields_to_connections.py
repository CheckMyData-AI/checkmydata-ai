"""add MCP fields to connections

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-03-18

"""

from alembic import op
import sqlalchemy as sa

revision = "r3s4t5u6v7w8"
down_revision = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.add_column(sa.Column("mcp_server_command", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mcp_server_args", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mcp_server_url", sa.String(1024), nullable=True))
        batch_op.add_column(sa.Column("mcp_transport_type", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("mcp_env_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_column("mcp_env_encrypted")
        batch_op.drop_column("mcp_transport_type")
        batch_op.drop_column("mcp_server_url")
        batch_op.drop_column("mcp_server_args")
        batch_op.drop_column("mcp_server_command")
