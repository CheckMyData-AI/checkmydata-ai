"""Unit tests for :class:`BM25Index` (M3)."""

from __future__ import annotations

import pickle

import pytest

from app.knowledge.bm25_index import BM25Index, tokenize_code


@pytest.fixture
def bm25_dir(tmp_path):
    return tmp_path / "bm25"


def test_tokenize_camel_and_snake_case():
    assert "user" in tokenize_code("UserService")
    assert "service" in tokenize_code("UserService")
    assert "validate" in tokenize_code("validate_email_address")
    assert "email" in tokenize_code("validate_email_address")


def test_tokenize_drops_stopwords_and_short_tokens():
    out = tokenize_code("the a function with x")
    assert "the" not in out
    assert "x" not in out
    assert "function" in out


def test_tokenize_token_cap_respected():
    huge = " ".join([f"identifier_{i}" for i in range(2000)])
    out = tokenize_code(huge)
    # Cap is 1024 in module constants.
    assert len(out) <= 1024


def test_build_and_query_roundtrip(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    docs = [
        ("doc1", "def analyze_query(): pass", {"source_path": "a.py"}),
        ("doc2", "class UserService: ...", {"source_path": "b.py"}),
        ("doc3", "function validateEmailAddress(){}", {"source_path": "c.js"}),
        ("doc4", "TODO: refactor this later", {"source_path": "d.md"}),
    ]
    bm25.build("proj-1", indexed_sha="abc123", documents=docs)
    hits = bm25.query("proj-1", "analyze query")
    assert hits, "expected at least one hit"
    assert hits[0]["id"] == "doc1"
    # Metadata round-trips through pickle.
    assert hits[0]["metadata"]["source_path"] == "a.py"


def test_query_with_no_snapshot_returns_empty(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    assert bm25.query("missing-project", "anything") == []


def test_build_is_atomic_no_tmp_leftover(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    docs = [("d", "alpha beta gamma", {})]
    bm25.build("p", indexed_sha="s", documents=docs)
    # No `.tmp` file should remain after a successful build.
    tmp_files = list(bm25_dir.glob("*.tmp"))
    assert tmp_files == []
    # The persisted file should be pickleable.
    pkl_files = list(bm25_dir.glob("*.pkl"))
    assert len(pkl_files) == 1
    with pkl_files[0].open("rb") as fh:
        loaded = pickle.load(fh)
    assert loaded.indexed_sha == "s"


def test_indexed_sha_returns_value_after_build(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    bm25.build("p", indexed_sha="sha-xyz", documents=[("d", "x y z", {})])
    assert bm25.indexed_sha("p") == "sha-xyz"
    assert bm25.indexed_sha("other") is None


def test_delete_removes_snapshot(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    bm25.build("p", indexed_sha="s", documents=[("d", "alpha beta", {})])
    assert bm25.indexed_sha("p") == "s"
    bm25.delete("p")
    assert bm25.indexed_sha("p") is None


def test_empty_corpus_produces_no_results(bm25_dir):
    bm25 = BM25Index(bm25_dir)
    bm25.build("p", indexed_sha="s", documents=[])
    assert bm25.query("p", "anything") == []


# ---------------------------------------------------------------------------
# F-KNOW-07: why the leg was empty, not just that it was
# ---------------------------------------------------------------------------


#: BM25's IDF is zero for a term present in every document, so a one-document
#: index returns nothing for any query. Tests needing hits need a real corpus.
_CORPUS = [
    ("c1", "analyze_query function with a docstring", {}),
    ("c2", "UserService class managing users", {}),
    ("c3", "validate email format helper", {}),
]


class TestEmptyReason:
    """``[]`` had five causes and one of them is healthy.

    A missing snapshot means hybrid retrieval is dense-only for this project
    until a reindex; a query that matches nothing means the index is working.
    Both returned ``[]``, and the caller labelled both ``empty_result``.
    """

    def test_absent_snapshot_is_named(self, bm25_dir):
        hits, reason = BM25Index(bm25_dir).query_with_reason("never-built", "anything")
        assert hits == []
        assert reason == "no_snapshot"

    def test_healthy_no_match_is_not_a_miss(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        hits, reason = bm25.query_with_reason("p", "zzzz_unrelated_identifier")
        assert hits == []
        assert reason == "no_match", "a working index that matched nothing is not degraded"

    def test_hits_report_ok(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        hits, reason = bm25.query_with_reason("p", "analyze_query")
        assert hits and reason == "ok"

    def test_corrupt_snapshot_is_named(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=[("c1", "alpha beta", {})])
        bm25._snapshots.clear()  # force a re-read from disk
        bm25._path("p").write_bytes(b"not a pickle")
        hits, reason = bm25.query_with_reason("p", "alpha")
        assert hits == []
        assert reason == "corrupt"

    def test_schema_mismatch_is_named(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=[("c1", "alpha beta", {})])
        snap = bm25.load("p")
        assert snap is not None
        object.__setattr__(snap, "schema_version", snap.schema_version + 99)
        bm25._path("p").write_bytes(pickle.dumps(snap))
        bm25._snapshots.clear()
        hits, reason = bm25.query_with_reason("p", "alpha")
        assert hits == []
        assert reason == "schema_mismatch"

    def test_untokenizable_query_is_named(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=[("c1", "alpha beta", {})])
        hits, reason = bm25.query_with_reason("p", "a the x")  # all stopwords/short
        assert hits == []
        assert reason == "no_query_tokens"

    def test_query_keeps_its_list_only_contract(self, bm25_dir):
        """Existing callers must be untouched by the new channel."""
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        out = bm25.query("p", "analyze_query")
        assert isinstance(out, list) and out and isinstance(out[0], dict)
