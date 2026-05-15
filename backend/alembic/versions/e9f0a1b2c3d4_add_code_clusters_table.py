"""add code clusters table (M6)

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cluster_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("symbol_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("table_names_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("file_paths_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("code_clusters") as batch_op:
        batch_op.create_index("ix_code_clusters_project", ["project_id"])
        batch_op.create_unique_constraint(
            "uq_code_clusters_project_cluster", ["project_id", "cluster_id"]
        )

    # cluster_id on code_graph_symbols was added in the M2 migration; here we
    # only ensure an index exists so cluster-scoped queries are cheap.
    with op.batch_alter_table("code_graph_symbols") as batch_op:
        batch_op.create_index(
            "ix_code_graph_symbols_cluster", ["project_id", "cluster_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("code_graph_symbols") as batch_op:
        batch_op.drop_index("ix_code_graph_symbols_cluster")
    op.drop_table("code_clusters")
