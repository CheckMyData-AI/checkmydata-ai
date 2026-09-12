"""Make the migrated schema match the models it is supposed to describe.

DATA-02, DATA-03, DATA-04, DATA-07, DATA-08, DATA-09.

The tests build their schema with `Base.metadata.create_all` and production builds it
with Alembic, so where the two disagree every test in the suite exercises a database
that does not exist. This revision makes the second agree with the first, because the
models are what the application code is written against, what `create_all` builds, and
what `autogenerate` compares to — three readers of four.

**PostgreSQL only, deliberately.** SQLite cannot `ALTER COLUMN`, cannot add a CHECK to
an existing table, and has no expression-index-on-JSONB to add; a dev database there is
built by `create_all` from the very models this revision is aligning to, so it is
already correct and there is nothing to do. The no-op is the honest outcome, not a gap.

Revision ID: a3b4c5d6e7f9
Revises: d0e1f2a3b4c5
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f9"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _nullable_columns(bind: sa.engine.Connection) -> set[tuple[str, str]]:
    """`(table, column)` for everything the live schema currently allows NULL in."""
    rows = bind.execute(
        sa.text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND is_nullable = 'YES'"
        )
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def upgrade() -> None:
    if not _is_postgres():
        logger.info("schema alignment: not PostgreSQL, nothing to align")
        return

    bind = op.get_bind()

    # --- DATA-03: a 64-bit vendor row estimate needs a 64-bit column -----------
    op.alter_column(
        "db_index",
        "row_count",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )

    # --- DATA-07: one name, one object ----------------------------------------
    # The table already carries `uq_mcp_api_keys_token_hash` (a UniqueConstraint with
    # its own implicit index). The plain index of the model's name is the redundant
    # second btree on the same 64-char column.
    op.execute(sa.text("DROP INDEX IF EXISTS ix_mcp_api_keys_token_hash"))

    # --- DATA-08: dedup that applies to system-scoped errors too ---------------
    # Both engines treat NULLs as distinct in a unique index, and `project_id` is
    # nullable for `source='system'` and span events — so the rule imposed nothing on
    # exactly those rows. Coalesced, as `uq_indexing_runs_active_one` already is.
    #
    # Rows that were duplicates only because of the NULL asymmetry must merge before
    # the index can be created, or it fails on existing data.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY coalesce(project_id, ''), signature
                           ORDER BY last_seen_at DESC, id
                       ) AS rn,
                       sum(occurrences) OVER (
                           PARTITION BY coalesce(project_id, ''), signature
                       ) AS total
                FROM error_log
            )
            UPDATE error_log e
            SET occurrences = r.total
            FROM ranked r
            WHERE e.id = r.id AND r.rn = 1
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM error_log e
            USING (
                SELECT id, row_number() OVER (
                    PARTITION BY coalesce(project_id, ''), signature
                    ORDER BY last_seen_at DESC, id
                ) AS rn
                FROM error_log
            ) r
            WHERE e.id = r.id AND r.rn > 1
            """
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS uq_error_log_project_sig"))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_error_log_project_sig "
            "ON error_log (coalesce(project_id, ''), signature)"
        )
    )

    # --- DATA-09: the delete path filters on two keys with OR ------------------
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_doc_embeddings_path "
            "ON doc_embeddings (project_id, (metadata ->> 'path'))"
        )
    )

    # --- DATA-04: the status vocabulary is load-bearing ------------------------
    # The partial unique index enforcing one active run per (project, kind,
    # connection) is scoped by a literal list of three of these strings, so a value
    # outside the vocabulary escapes the guard while still reading as active to every
    # Python caller. Rows are repaired first: an out-of-vocabulary status is not a
    # run anybody can act on, and `failed` is the terminal state that says so.
    from app.models.indexing_run import STATUS_VOCABULARY

    vocabulary = ", ".join(f"'{s}'" for s in STATUS_VOCABULARY)
    repaired = bind.execute(
        sa.text(f"UPDATE indexing_runs SET status = 'failed' WHERE status NOT IN ({vocabulary})")
    ).rowcount
    if repaired:
        logger.warning(
            "schema alignment: %d indexing_runs row(s) held a status outside the "
            "vocabulary and were marked failed",
            repaired,
        )
    op.execute(
        sa.text("ALTER TABLE indexing_runs DROP CONSTRAINT IF EXISTS ck_indexing_runs_status")
    )
    op.execute(
        sa.text(
            f"ALTER TABLE indexing_runs ADD CONSTRAINT ck_indexing_runs_status "
            f"CHECK (status IN ({vocabulary}))"
        )
    )

    # --- DATA-02: nullability, derived from the models -------------------------
    from app.ops.schema_alignment import columns_requiring_not_null

    live_nullable = _nullable_columns(bind)
    tightened = 0
    for table, column, fill in columns_requiring_not_null():
        if (table, column) not in live_nullable:
            continue
        filled = bind.execute(
            sa.text(f'UPDATE "{table}" SET "{column}" = {fill} WHERE "{column}" IS NULL')
        ).rowcount
        if filled:
            # Loud, because a fill is the migration deciding what a row means. On a
            # column that has carried a server default since it was created the
            # honest expectation is zero, and anything else is a thing to look at.
            logger.warning(
                "schema alignment: %s.%s had %d NULL row(s), filled with %s",
                table,
                column,
                filled,
                fill,
            )
        op.execute(sa.text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL'))
        tightened += 1
    logger.info("schema alignment: %d column(s) tightened to NOT NULL", tightened)


def downgrade() -> None:
    """Only what can be undone without inventing data.

    The NOT NULL sweep is deliberately not reversed: relaxing a column is safe, but
    there is no record of which ones this revision tightened versus which were already
    correct, and guessing would loosen constraints the schema has had since it was
    created.
    """
    if not _is_postgres():
        return
    op.execute(
        sa.text("ALTER TABLE indexing_runs DROP CONSTRAINT IF EXISTS ck_indexing_runs_status")
    )
    op.execute(sa.text("DROP INDEX IF EXISTS ix_doc_embeddings_path"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_error_log_project_sig"))
    op.execute(
        sa.text("CREATE UNIQUE INDEX uq_error_log_project_sig ON error_log (project_id, signature)")
    )
    op.alter_column(
        "db_index",
        "row_count",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
