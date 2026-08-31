"""doc_embeddings.id: a chunk id is not bounded by 512 characters

Revision ID: 451d6ca545f5
Revises: 7a8925ee9104
Create Date: 2026-08-31

Production, 2026-08-31, during the first full rebuild after the PHP extraction fix::

    code_symbol_chunker: failed to upsert 200 chunks for project 38856e63
    psycopg.errors.StringDataRightTruncation: value too long for
    type character varying(512)

Code-symbol vectors were being dropped in batches of 200, silently — the chunker
catches the failure and logs a WARNING, so the rebuild ran to completion while storing
nothing for the symbols that overflowed.

The id is ``f"sym:{rel_path}:{symbol.uid}{suffix}:{chunk_idx}"``, and
``symbol.uid`` already begins with that same path (``{lang}:{path}:{kind}:{scope.}{name}``
since SYMBOL_UID_SCHEMA 2) — so the path is present twice. Measured against the real
repository: symbol uids reach 316 characters and the longest id that fit was 497, which
is how a 512 cap looked survivable right up to the deep PHP module paths that broke it.

Widened rather than shortened, deliberately. Removing the duplicated path would change
every id, and an incremental run merges by id — so the old rows would linger as
unreachable duplicates until a clean rebuild, trading a loud failure for a quiet one.
Text has no storage or lookup penalty over varchar in Postgres; the only real bound is
the btree entry limit (~2 704 bytes), far above anything a path can produce.

Postgres only: the table itself does not exist on SQLite (see 1d72054cd637).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "451d6ca545f5"
down_revision = "7a8925ee9104"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.alter_column(
        "doc_embeddings",
        "id",
        existing_type=sa.String(512),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    # Rows longer than 512 cannot survive the narrowing; they are re-derivable by a
    # re-index, and failing loudly here beats truncating an id into a collision.
    op.execute("DELETE FROM doc_embeddings WHERE length(id) > 512")
    op.alter_column(
        "doc_embeddings",
        "id",
        existing_type=sa.Text(),
        type_=sa.String(512),
        existing_nullable=False,
    )
