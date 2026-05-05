"""Add tenancy hot-path indexes (T34).

Adds covering indexes on ``connections.project_id`` and ``projects.owner_id``,
which are scanned on every ``list_by_project`` / ``get_accessible_projects``
call. Both queries currently fall back to FK index lookups that, on Postgres,
do not always satisfy the planner for the access patterns we use.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-05-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def _has_index(inspector, table: str, name: str) -> bool:
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = __import__("sqlalchemy").inspect(bind)

    if not _has_index(inspector, "connections", "ix_connections_project_id"):
        op.create_index(
            "ix_connections_project_id",
            "connections",
            ["project_id"],
            unique=False,
        )

    if not _has_index(inspector, "projects", "ix_projects_owner_id"):
        op.create_index(
            "ix_projects_owner_id",
            "projects",
            ["owner_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = __import__("sqlalchemy").inspect(bind)

    if _has_index(inspector, "projects", "ix_projects_owner_id"):
        op.drop_index("ix_projects_owner_id", table_name="projects")

    if _has_index(inspector, "connections", "ix_connections_project_id"):
        op.drop_index("ix_connections_project_id", table_name="connections")
