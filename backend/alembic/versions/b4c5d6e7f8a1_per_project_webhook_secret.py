"""A webhook secret that belongs to one repository, not to the deployment.

AUTH-05. `POST /api/repos/{project_id}/webhook` verified the body's HMAC against one
process-wide `GIT_WEBHOOK_SECRET`, and nothing bound that secret to the project id in
the path — so the signature proved "someone holds the deployment's secret" and never
"someone controls this project's repository". Every tenant who wired a webhook was
given the same string, and could then sign a body for anybody else's project id.

The column is nullable and there is no backfill, deliberately: inventing a secret for
a repository nobody has configured would create a credential nobody knows, and copying
the global one into every row would preserve exactly the property being removed. A
repository with no secret refuses every webhook until its owner mints one.

Revision ID: b4c5d6e7f8a1
Revises: a3b4c5d6e7f9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4c5d6e7f8a1"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_repositories",
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_repositories", "webhook_secret_encrypted")
