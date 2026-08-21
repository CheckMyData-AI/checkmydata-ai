"""Unit tests for :class:`BM25Index` (M3)."""

from __future__ import annotations

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
    # F-KNOW-06 replaced the pickle with gzip JSON. The assertion — one persisted file,
    # readable, carrying the SHA — is unchanged; only the reader is.
    import gzip
    import json

    written = list(bm25_dir.glob("*.json.gz"))
    assert len(written) == 1
    with gzip.open(written[0], "rt", encoding="utf-8") as fh:
        loaded = json.load(fh)
    assert loaded["indexed_sha"] == "s"


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
        import gzip
        import json

        path = bm25._path("p")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["schema_version"] = payload["schema_version"] + 99
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
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


# ---------------------------------------------------------------------------
# F-KNOW-06: pickle.load on a snapshot is a latent RCE primitive
# ---------------------------------------------------------------------------


class TestNoPickle:
    """The row asked for this **before** F-KNOW-07. It was done after, and F-KNOW-12
    widened the exposure in between — the boot reconcile now reads a snapshot in both
    the web and the worker process, on every start.

    `pickle.load` executes whatever the payload says. Today the file is written by the
    app to its own local disk, which is why the row says *latent* — but the directory
    is configurable (`BM25_DATA_DIR`), and the shared-storage fix that F-KNOW-12
    nearly took would have put it on a volume several processes can write.
    """

    def test_the_module_does_not_import_pickle_at_all(self):
        """Unused is not the same as absent.

        A module that still imports `pickle` invites the next person to reach for it,
        and a grep for the primitive keeps finding a hit. The assertion is on the
        import graph, not on a call site.
        """
        import ast
        import inspect

        from app.knowledge import bm25_index

        tree = ast.parse(inspect.getsource(bm25_index))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "pickle" not in imported, "the primitive must be gone, not merely unused"

    def test_the_snapshot_on_disk_is_not_a_pickle(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        written = [f for f in bm25_dir.iterdir() if f.is_file()]
        assert written, "nothing was persisted"
        assert not any(f.suffix == ".pkl" for f in written)
        raw = written[0].read_bytes()
        assert raw[:2] == b"\x1f\x8b", "expected gzip, so the payload is data not opcodes"

    def test_a_legacy_pickle_is_never_loaded(self, bm25_dir):
        """Not even once, not even to migrate.

        Reading it "just for the upgrade" keeps the primitive alive for exactly the
        window an attacker needs. Snapshots are derived data (F-KNOW-12), so the
        correct upgrade path is to rebuild, which the boot reconcile does for free.
        """
        import pickle as _pickle

        bm25_dir.mkdir(parents=True, exist_ok=True)
        legacy = bm25_dir / "p.pkl"
        legacy.write_bytes(_pickle.dumps({"anything": "at all"}))

        bm25 = BM25Index(bm25_dir)
        hits, reason = bm25.query_with_reason("p", "alpha")
        assert hits == []
        assert reason == "no_snapshot", "a leftover .pkl must read as absent, not as data"

    def test_a_legacy_pickle_is_removed_when_the_snapshot_is_rebuilt(self, bm25_dir):
        import pickle as _pickle

        bm25_dir.mkdir(parents=True, exist_ok=True)
        (bm25_dir / "p.pkl").write_bytes(_pickle.dumps({"x": 1}))

        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        assert not (bm25_dir / "p.pkl").exists(), "the primitive should not be left on disk"

    def test_a_legacy_pickle_is_removed_on_delete(self, bm25_dir):
        import pickle as _pickle

        bm25_dir.mkdir(parents=True, exist_ok=True)
        (bm25_dir / "p.pkl").write_bytes(_pickle.dumps({"x": 1}))
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        bm25.delete("p")
        assert not (bm25_dir / "p.pkl").exists()
        assert not list(bm25_dir.glob("p.json*"))

    def test_ranking_survives_the_format_change(self, bm25_dir):
        """Reconstructing BM25 from stored tokens must not reorder results."""
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        in_memory = [h["id"] for h in bm25.query("p", "analyze_query")]

        reloaded = BM25Index(bm25_dir)  # forces a read from disk
        from_disk = [h["id"] for h in reloaded.query("p", "analyze_query")]
        assert from_disk == in_memory and from_disk, from_disk

    def test_metadata_and_documents_survive_the_round_trip(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build(
            "p",
            indexed_sha="sha",
            documents=[
                ("c1", "analyze_query function", {"source_path": "a.py", "n": 3}),
                ("c2", "UserService class", {"source_path": "b.py"}),
                ("c3", "validate email", {}),
            ],
        )
        hit = BM25Index(bm25_dir).query("p", "analyze_query")[0]
        assert hit["id"] == "c1"
        assert hit["document"] == "analyze_query function"
        assert hit["metadata"]["source_path"] == "a.py"
        assert hit["metadata"]["n"] == 3

    def test_a_corrupt_snapshot_reads_as_corrupt(self, bm25_dir):
        bm25 = BM25Index(bm25_dir)
        bm25.build("p", indexed_sha="sha", documents=_CORPUS)
        bm25._snapshots.clear()
        bm25._path("p").write_bytes(b"not gzip, not json")
        hits, reason = bm25.query_with_reason("p", "analyze_query")
        assert hits == [] and reason == "corrupt"
