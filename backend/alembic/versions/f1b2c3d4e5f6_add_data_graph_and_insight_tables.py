"""add data graph (metric_definitions, metric_relationships) and insight
(insight_records, trust_scores) tables for the foundation layer

Revision ID: f1b2c3d4e5f6
Revises: a2b3c4d5e6f7, g4h5i6j7k8l9
Create Date: 2026-03-22
"""

import sqlalchemy as sa

from alembic import op

revision = "f1b2c3d4e5f6"
down_revision = ("a2b3c4d5e6f7", "g4h5i6j7k8l9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("category", sa.String(100), server_default="general"),
        sa.Column("source_table", sa.String(255), nullable=True),
        sa.Column("source_column", sa.String(255), nullable=True),
        sa.Column("aggregation", sa.String(50), server_default=""),
        sa.Column("formula", sa.Text(), server_default=""),
        sa.Column("unit", sa.String(50), server_default=""),
        sa.Column("data_type", sa.String(50), server_default="numeric"),
        sa.Column("discovery_source", sa.String(50), server_default="auto"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("times_referenced", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", "connection_id", name="uq_metric_def_project_name_conn"),
    )

    op.create_table(
        "metric_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "metric_a_id",
            sa.String(36),
            sa.ForeignKey("metric_definitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "metric_b_id",
            sa.String(36),
            sa.ForeignKey("metric_definitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("strength", sa.Float(), server_default="0.0"),
        sa.Column("direction", sa.String(20), server_default="bidirectional"),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("evidence", sa.Text(), server_default=""),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("metric_a_id", "metric_b_id", "relationship_type", name="uq_metric_rel_pair_type"),
    )

    op.create_table(
        "insight_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("insight_type", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), server_default="info"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), server_default="[]"),
        sa.Column("source_metrics_json", sa.Text(), server_default="[]"),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column("recommended_action", sa.Text(), server_default=""),
        sa.Column("expected_impact", sa.Text(), server_default=""),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("status", sa.String(30), server_default="active", index=True),
        sa.Column("user_verdict", sa.String(30), nullable=True),
        sa.Column("user_feedback", sa.Text(), nullable=True),
        sa.Column("times_surfaced", sa.Integer(), server_default="1"),
        sa.Column("times_confirmed", sa.Integer(), server_default="0"),
        sa.Column("times_dismissed", sa.Integer(), server_default="0"),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "trust_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "insight_id",
            sa.String(36),
            sa.ForeignKey("insight_records.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("data_freshness_hours", sa.Float(), server_default="0.0"),
        sa.Column("sources_json", sa.Text(), server_default="[]"),
        sa.Column("validation_method", sa.String(100), server_default="auto"),
        sa.Column("validation_details", sa.Text(), server_default=""),
        sa.Column("cross_validated", sa.Boolean(), server_default="0"),
        sa.Column("sample_size", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("trust_scores")
    op.drop_table("insight_records")
    op.drop_table("metric_relationships")
    op.drop_table("metric_definitions")
