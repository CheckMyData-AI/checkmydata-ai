"""migrate existing project repo_url data to project_repositories

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-03-18

"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "q2r3s4t5u6v7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    projects = conn.execute(
        sa.text("SELECT id, name, repo_url, repo_branch, ssh_key_id FROM projects WHERE repo_url IS NOT NULL AND repo_url != ''")
    ).fetchall()

    for row in projects:
        repo_id = str(uuid.uuid4())
        repo_name = f"{row[1]} repo" if row[1] else "Primary repo"
        conn.execute(
            sa.text(
                "INSERT INTO project_repositories (id, project_id, name, provider, repo_url, branch, ssh_key_id, indexing_status) "
                "VALUES (:id, :project_id, :name, :provider, :repo_url, :branch, :ssh_key_id, :status)"
            ),
            {
                "id": repo_id,
                "project_id": row[0],
                "name": repo_name,
                "provider": "git_ssh",
                "repo_url": row[2],
                "branch": row[3] or "main",
                "ssh_key_id": row[4],
                "status": "idle",
            },
        )


def downgrade() -> None:
    pass
