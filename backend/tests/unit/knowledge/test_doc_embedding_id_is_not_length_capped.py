"""A code-symbol chunk id outgrew the column, and the loss was silent.

Production, 2026-08-31, during the first full rebuild after the PHP extraction fix::

    code_symbol_chunker: failed to upsert 200 chunks for project 38856e63
    psycopg.errors.StringDataRightTruncation: value too long for
    type character varying(512)

The chunker catches that and logs a WARNING, so the rebuild ran to completion while
storing nothing for every symbol that overflowed — a warning per 200 chunks is the only
trace, and `code_symbol_embed` reported success.

The id is ``f"sym:{rel_path}:{symbol.uid}{suffix}:{chunk_idx}"``, and `symbol.uid` already
opens with that same path (`{lang}:{path}:{kind}:{scope.}{name}` since SYMBOL_UID_SCHEMA
2), so the path is counted twice. Measured against the real repository: uids reach 316
characters and the longest id that fitted was 497 — which is exactly why a 512 cap looked
survivable until the deep PHP module paths arrived.

Widened rather than de-duplicated on purpose: changing the id would leave the old rows as
unreachable duplicates until a clean rebuild, because an incremental run merges by id.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.models.doc_embedding import DocEmbedding


def test_the_id_column_has_no_length_cap() -> None:
    col = DocEmbedding.__table__.c.id
    length = getattr(col.type, "length", None)
    assert length is None, (
        f"doc_embeddings.id is capped at {length}; a code-symbol chunk id carries the "
        "file path twice (once as its own prefix, once inside the symbol UID) and "
        "production produced ids past 512 characters, which were dropped in batches of "
        "200 with only a WARNING to show for it"
    )


def test_a_realistic_worst_case_id_is_longer_than_the_old_cap() -> None:
    """Built from the lengths measured in the real repository, not from a guess — the
    first version of this fixture was 437 characters and proved nothing.

    Production: 25 538 symbols, of which exactly **three** produce an id over 512, the
    longest 518. Three is not the damage. The write is one `INSERT … SELECT unnest(…)`
    statement per batch, so a single oversized id fails the whole batch — the log reads
    `failed to upsert 200 chunks`, and 199 innocent vectors go with it.
    """
    # Five repeats, not four: four gives 442 characters and passes the old cap. The
    # arithmetic is worth doing rather than eyeballing — the real worst case is 518,
    # so a fixture built by guess lands under it as easily as over.
    rel_path = "api/app/Modules/" + "Submodules/Provider/Application/UseCases/" * 5 + "X.php"
    uid = f"php:{rel_path}:method:CreateKycVerificationRequestForMultipleNumbers.handle"
    doc_id = f"sym:{rel_path}:{uid}:0"
    assert len(doc_id) > 512, (
        f"the fixture no longer reproduces the overflow ({len(doc_id)} chars); it must, "
        "or this file stops guarding anything"
    )


def test_one_oversized_id_costs_its_whole_batch() -> None:
    """Why three bad symbols mattered: the flush is a single statement over an unnest of
    the batch, so any row that violates a constraint takes the batch with it. That is a
    deliberate trade for write speed — a per-row write measured 167 ms of fixed cost each
    — and it is the reason a length cap on one column was worth a migration rather than a
    shrug."""
    import inspect

    from app.knowledge import pgvector_store

    source = inspect.getsource(pgvector_store)
    assert "unnest(" in source, (
        "the batch write changed shape; if it is now per-row, the blast radius of one "
        "bad id is no longer a batch and this test's premise needs re-checking"
    )


def test_the_migration_widens_rather_than_truncates() -> None:
    """Truncating an id would collide two symbols onto one row — a wrong vector served
    confidently, which is worse than a missing one."""
    import pathlib

    migration = next(
        p
        for p in (pathlib.Path(__file__).parents[3] / "alembic" / "versions").glob("*.py")
        if "doc_embedding_id_is_not_512" in p.name
    )
    source = migration.read_text(encoding="utf-8")
    assert "type_=sa.Text()" in source
    assert "substring" not in source.lower() and "left(" not in source.lower()


def test_it_still_round_trips_through_the_model() -> None:
    long_id = "sym:" + ("a/" * 300) + "x.php:0"
    row = DocEmbedding(project_id="p", id=long_id, document="d", doc_metadata={}, embedding=[0.0])
    assert row.id == long_id
    assert isinstance(DocEmbedding.__table__.c.id.type, sa.Text)
