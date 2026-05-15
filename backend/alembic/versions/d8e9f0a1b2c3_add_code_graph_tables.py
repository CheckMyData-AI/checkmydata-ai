"""add code graph tables (M2)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_graph_symbols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uid", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False, server_default="0"),
        sa.Column("end_line", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parent_uid", sa.String(512), nullable=True),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("decorators_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("signature", sa.Text, nullable=False, server_default=""),
        sa.Column("docstring", sa.Text, nullable=False, server_default=""),
        sa.Column("cluster_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("code_graph_symbols") as batch_op:
        batch_op.create_index("ix_code_graph_symbols_project", ["project_id"])
        batch_op.create_index(
            "ix_code_graph_symbols_project_name", ["project_id", "name"]
        )
        batch_op.create_index(
            "ix_code_graph_symbols_project_file", ["project_id", "file_path"]
        )
        batch_op.create_index("ix_code_graph_symbols_uid", ["uid"])

    op.create_table(
        "code_graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("src_uid", sa.String(512), nullable=False),
        sa.Column("dst_uid", sa.String(512), nullable=False),
        sa.Column("edge_type", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("attrs_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("code_graph_edges") as batch_op:
        batch_op.create_index("ix_code_graph_edges_project", ["project_id"])
        batch_op.create_index("ix_code_graph_edges_src", ["project_id", "src_uid"])
        batch_op.create_index("ix_code_graph_edges_dst", ["project_id", "dst_uid"])
        batch_op.create_index("ix_code_graph_edges_type", ["project_id", "edge_type"])


def downgrade() -> None:
    op.drop_table("code_graph_edges")
    op.drop_table("code_graph_symbols")
