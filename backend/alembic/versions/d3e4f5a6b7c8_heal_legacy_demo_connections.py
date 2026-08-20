"""Point pre-fix demo connections at a real file instead of ``:memory:``.

Found by the post-deploy check for the demo work, not by a test: production held one
connection with ``db_type='sqlite'`` and ``db_name=':memory:'``, created 2026-06-05.

Before that release it failed with ``Unsupported adapter: sqlite``; after it, the new
connector **refuses** ``:memory:`` at connect — a better error for the same empty screen.
So F-EXP-01's promise ("the demo path sets up sample data") was true for connections made
after the fix and false for every one made before it, which is the half of a fix that a
test suite cannot see.

The rewrite is all this needs. Once ``db_name`` points inside ``DEMO_DB_DIR``,
``ConnectionService.to_config`` seeds the file through ``repair_demo_db_if_missing`` on
the next config build — the same self-completing shape the embedding reconcile uses, so
there is no operator step and no user action. The owner's id is what names the file,
matching ``demo_data.demo_db_path``.

``is_read_only`` is flipped in the same statement: these rows predate F-EXP-02 and were
created writable.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

#: Kept in step with ``settings.demo_db_dir``'s default. A migration cannot read the
#: setting — it runs before the app — and hardcoding the default is honest here: a
#: deployment that overrode it will have its file seeded at the overridden path anyway,
#: because `repair_demo_db_if_missing` resolves the directory at call time and a path
#: outside it is simply left alone rather than healed.
_DEMO_DIR = "./data/demo"


def upgrade() -> None:
    connections = sa.table(
        "connections",
        sa.column("id", sa.String),
        sa.column("project_id", sa.String),
        sa.column("db_type", sa.String),
        sa.column("db_name", sa.String),
        sa.column("is_read_only", sa.Boolean),
    )
    projects = sa.table(
        "projects",
        sa.column("id", sa.String),
        sa.column("owner_id", sa.String),
    )

    owner = (
        sa.select(projects.c.owner_id)
        .where(projects.c.id == connections.c.project_id)
        .scalar_subquery()
    )
    op.execute(
        connections.update()
        .where(
            sa.and_(
                connections.c.db_type == "sqlite",
                connections.c.db_name == ":memory:",
            )
        )
        .values(
            db_name=_DEMO_DIR + "/demo_" + owner + ".db",
            is_read_only=True,
        )
    )


def downgrade() -> None:
    """Put the rows back to ``:memory:``.

    Reversible in the only sense that matters: the demo's sample data is derived from
    nothing and rebuilt on demand, so nothing is lost by pointing these back at a target
    that cannot hold data. Scoped by the path prefix so a connection somebody aimed at a
    file of their own is never touched.

    ``is_read_only`` is deliberately **not** reverted. Making a connection writable again
    is a privilege change, and a downgrade that hands one out to undo a path rewrite is
    doing something nobody asked it for. The asymmetry is the safe direction.
    """
    connections = sa.table(
        "connections",
        sa.column("db_type", sa.String),
        sa.column("db_name", sa.String),
    )
    op.execute(
        connections.update()
        .where(
            sa.and_(
                connections.c.db_type == "sqlite",
                connections.c.db_name.like(_DEMO_DIR + "/demo_%.db"),
            )
        )
        .values(db_name=":memory:")
    )
