"""An extractor change reaches only the files somebody happens to edit.

`save_incremental` merges by FILE, so an incremental run re-reads only what changed.
An extractor that starts seeing something new — PHP call sites, a PHP `use` statement,
a Ruby `require` — therefore leaves every untouched file carrying whatever the previous
extractor found, which for those languages was nothing. The graph stays wrong everywhere
except the handful of files that moved, indefinitely, and nothing reports it: an absent
edge and an edge that was never possible look identical.

Two extractor fixes shipped before this constant existed, and both were re-indexed by
hand. That is the manual step this retires: `GRAPH_EXTRACTION_SCHEMA` rides the
embedding fingerprint, so `reconcile_embeddings` enqueues one idempotent,
advisory-locked `force_full` rebuild at startup.

It is deliberately SEPARATE from `SYMBOL_UID_SCHEMA`. A symbol can keep its identity
while every edge around it changes; bumping the UID constant to force a rebuild would
be a constant lying about what moved, and the next reader would look for a UID change
that never happened.
"""

from __future__ import annotations

from unittest.mock import patch

from app.knowledge.ast_parser import GRAPH_EXTRACTION_SCHEMA, SYMBOL_UID_SCHEMA
from app.ops.embedding_reconcile import embedding_fingerprint


def _fingerprint() -> str:
    with patch("app.ops.embedding_reconcile.settings") as s:
        s.chroma_embedding_model = "m"
        s.embedder_max_tokens = 512
        return embedding_fingerprint()


def test_the_fingerprint_names_the_extraction_schema() -> None:
    assert f"gx{GRAPH_EXTRACTION_SCHEMA}" in _fingerprint(), (
        "an extractor change must move the fingerprint, or no deploy rebuilds the graph "
        "and the fix reaches only files that happen to be edited"
    )


def test_a_bump_changes_the_fingerprint() -> None:
    import importlib

    import app.ops.embedding_reconcile as mod

    before = _fingerprint()
    try:
        with patch("app.knowledge.ast_parser.GRAPH_EXTRACTION_SCHEMA", GRAPH_EXTRACTION_SCHEMA + 1):
            importlib.reload(mod)
            with patch.object(mod, "settings") as s:
                s.chroma_embedding_model = "m"
                s.embedder_max_tokens = 512
                after = mod.embedding_fingerprint()
    finally:
        # OUTSIDE the patch, and in a finally: reloading while the constant is still
        # patched re-imports the patched value and leaves every later test reading it.
        importlib.reload(mod)
    assert before != after, "bumping the extraction schema left the fingerprint unchanged"
    assert _fingerprint() == before, "the reload left the bumped value behind"


def test_it_is_not_the_same_constant_as_the_uid_schema() -> None:
    """They answer different questions and must be bumpable independently. Sharing one
    would mean a UID change forcing a graph rebuild it does not need, or an extractor
    change bumping a constant whose docstring describes UID shape."""
    fp = _fingerprint()
    assert f"uid{SYMBOL_UID_SCHEMA}" in fp
    assert f"gx{GRAPH_EXTRACTION_SCHEMA}" in fp
    assert "uid" in fp and "gx" in fp and fp.index("uid") != fp.index("gx")


def test_the_current_bump_covers_the_php_and_ruby_extraction_fixes() -> None:
    """The constant is only useful if it was actually moved by the change that needed
    it. Version 1 is everything through 2026-08-30, before PHP calls and PHP/Ruby
    imports could resolve at all."""
    assert GRAPH_EXTRACTION_SCHEMA >= 2, (
        "the PHP/Ruby extraction fixes shipped without moving the schema, so production "
        "keeps the old (empty) extraction for every file that does not change"
    )
