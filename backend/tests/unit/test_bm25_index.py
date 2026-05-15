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
