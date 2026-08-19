"""AUD-0819-02 / D3: the UID format change reindexes itself.

Method UIDs gained their enclosing scope, so a symbol in a file that has not
changed keeps its old-format UID until that file changes. `save_incremental`
merges by FILE, not by UID (`code_graph_service.py`), so an edge from a changed
file to a method in an unchanged one dangles and is pruned. The index is correct
again only after a full rebuild.

Rather than adding a second reconcile marker, the symbol-UID schema version rides
the embedding fingerprint that already exists: a changed fingerprint makes
`reconcile_embeddings` enqueue one idempotent, multi-dyno-safe full reindex at
startup (`app/ops/embedding_reconcile.py`), and `queue_embedding_reindex` passes
`force_full=True`, which is exactly the clean rebuild required. The deploy
completes itself; no operator step is owed.

Ordering matters and is deliberate: this bump ships AFTER the embed-stage memory
fix (AUD-0819-01), because before it the forced reindex was the very run that got
SIGKILLed.
"""

from __future__ import annotations

from unittest.mock import patch

from app.knowledge.ast_parser import SYMBOL_UID_SCHEMA
from app.ops.embedding_reconcile import embedding_fingerprint


def test_fingerprint_names_the_symbol_uid_schema():
    with patch("app.ops.embedding_reconcile.settings") as s:
        s.chroma_embedding_model = "m"
        s.embedder_max_tokens = 512
        fp = embedding_fingerprint()
    assert f"uid{SYMBOL_UID_SCHEMA}" in fp, (
        "a UID-format change must move the fingerprint, or no deploy reindexes"
    )


def test_a_uid_schema_bump_changes_the_fingerprint():
    with patch("app.ops.embedding_reconcile.settings") as s:
        s.chroma_embedding_model = "m"
        s.embedder_max_tokens = 512
        before = embedding_fingerprint()
        with patch("app.ops.embedding_reconcile.SYMBOL_UID_SCHEMA", SYMBOL_UID_SCHEMA + 1):
            after = embedding_fingerprint()
    assert before != after


def test_the_model_and_window_still_move_it():
    """The pre-existing triggers must keep working — this is an addition."""
    with patch("app.ops.embedding_reconcile.settings") as s:
        s.chroma_embedding_model = "m"
        s.embedder_max_tokens = 512
        base = embedding_fingerprint()
        s.chroma_embedding_model = "other"
        assert embedding_fingerprint() != base
        s.chroma_embedding_model = "m"
        s.embedder_max_tokens = 256
        assert embedding_fingerprint() != base


def test_the_schema_version_is_an_int_above_one():
    # 1 was the implicit format before the scope was added; anything at or below
    # it would let an old marker read as current.
    assert isinstance(SYMBOL_UID_SCHEMA, int)
    assert SYMBOL_UID_SCHEMA >= 2
