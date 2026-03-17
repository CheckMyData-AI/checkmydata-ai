"""per-purpose LLM model configs

Revision ID: f1a2b3c4d5e6
Revises: c7d2e8f31a45
Create Date: 2026-03-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "d4f015eb8a1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLS = [
    ("indexing_llm_provider", sa.String(50)),
    ("indexing_llm_model", sa.String(100)),
    ("agent_llm_provider", sa.String(50)),
    ("agent_llm_model", sa.String(100)),
    ("sql_llm_provider", sa.String(50)),
    ("sql_llm_model", sa.String(100)),
]


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        for col_name, col_type in NEW_COLS:
            batch_op.add_column(sa.Column(col_name, col_type, nullable=True))

    # Copy existing default values into all three purpose-specific columns
    projects = sa.table(
        "projects",
        sa.column("default_llm_provider", sa.String),
        sa.column("default_llm_model", sa.String),
        sa.column("indexing_llm_provider", sa.String),
        sa.column("indexing_llm_model", sa.String),
        sa.column("agent_llm_provider", sa.String),
        sa.column("agent_llm_model", sa.String),
        sa.column("sql_llm_provider", sa.String),
        sa.column("sql_llm_model", sa.String),
    )
    op.execute(
        projects.update().values(
            indexing_llm_provider=projects.c.default_llm_provider,
            indexing_llm_model=projects.c.default_llm_model,
            agent_llm_provider=projects.c.default_llm_provider,
            agent_llm_model=projects.c.default_llm_model,
            sql_llm_provider=projects.c.default_llm_provider,
            sql_llm_model=projects.c.default_llm_model,
        )
    )

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("default_llm_provider")
        batch_op.drop_column("default_llm_model")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("default_llm_provider", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("default_llm_model", sa.String(100), nullable=True))

    projects = sa.table(
        "projects",
        sa.column("default_llm_provider", sa.String),
        sa.column("default_llm_model", sa.String),
        sa.column("agent_llm_provider", sa.String),
        sa.column("agent_llm_model", sa.String),
    )
    op.execute(
        projects.update().values(
            default_llm_provider=projects.c.agent_llm_provider,
            default_llm_model=projects.c.agent_llm_model,
        )
    )

    with op.batch_alter_table("projects") as batch_op:
        for col_name, _ in NEW_COLS:
            batch_op.drop_column(col_name)
