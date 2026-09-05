"""The identifier a person types was never a term in the index (row 2.3).

`tokenize_code` split `camelCase` and `snake_case` and appended **only the
components**, so `resolve_sync_status` was indexed as `resolve`, `sync`,
`status` — three ordinary English words — and the identifier itself existed
nowhere in the corpus.

The search still matched, which is why this is easy to miss. What was lost is
**precision**: a document where those three words co-occur by chance scored
alongside the one that defines the symbol. BM25 ranks by IDF, and the whole
identifier is a *rare* term while its parts are common ones — so emitting it is
exactly the signal the ranking was missing.

It matters more here than it would elsewhere, because of what the corpus turns
out to be. `KnowledgeDoc.content` is **LLM-generated documentation**, not source
(`pipeline_runner.py:1172` stores `generated_content`). The lexical leg has never
seen a line of code: an identifier reaches it only when the model happened to
write it into a summary. Splitting those few occurrences into common words spent
the only exact signal the leg had.

**The snapshot stores its tokenized corpus**, so a tokenizer change desynchronises
build from query — old tokens on disk, new tokens from the query. `_SCHEMA_VERSION`
is therefore bumped with it: `load()` rejects a mismatch, `indexed_sha` goes
through `load()`, and `bm25_local_reconcile` treats an unreadable snapshot as
missing. The change re-applies itself at boot from Postgres, with no clone and no
re-index.
"""

from __future__ import annotations

import pytest

from app.knowledge.bm25_index import tokenize_code


class TestTheWholeIdentifierSurvives:
    @pytest.mark.parametrize(
        ("text", "whole"),
        [
            ("resolve_sync_status", "resolve_sync_status"),
            ("getUserName", "getusername"),
            ("HybridRetriever", "hybridretriever"),
            ("code-db-sync", "code"),  # kebab splits on the non-word char, see below
        ],
    )
    def test_it_is_emitted_beside_its_parts(self, text, whole):
        tokens = tokenize_code(text)
        assert whole in tokens, f"{whole!r} missing from {tokens}"

    def test_the_parts_are_still_emitted(self):
        """Additive, not a replacement. Dropping the parts would lose every
        query that names a concept rather than a symbol."""
        tokens = tokenize_code("resolve_sync_status")
        assert {"resolve", "sync", "status"} <= set(tokens)

    def test_a_plain_word_is_not_duplicated(self):
        """`connection` has no components to add back; emitting it twice would
        double its term frequency and quietly bias the ranking."""
        assert tokenize_code("connection").count("connection") == 1

    def test_a_query_and_a_document_agree(self):
        """Same function both sides, so the whole identifier is matchable."""
        doc = tokenize_code("The resolve_sync_status helper decides the state.")
        query = tokenize_code("resolve_sync_status")
        assert "resolve_sync_status" in doc
        assert "resolve_sync_status" in query


class TestItStaysWithinTheExistingRules:
    def test_the_stopword_filter_still_applies_to_parts(self):
        tokens = tokenize_code("get_the_value")
        assert "the" not in tokens

    def test_a_short_component_is_still_dropped_but_the_whole_survives(self):
        """`db_index` — `db` clears the 2-char floor, and the whole name is the
        point of the change."""
        tokens = tokenize_code("db_index")
        assert "db_index" in tokens

    def test_the_per_document_cap_is_still_honoured(self):
        from app.knowledge.bm25_index import _MAX_TOKENS_PER_DOC

        tokens = tokenize_code(" ".join(f"some_symbol_{i}" for i in range(_MAX_TOKENS_PER_DOC)))
        assert len(tokens) <= _MAX_TOKENS_PER_DOC

    def test_empty_text_is_still_empty(self):
        assert tokenize_code("") == []


class TestTheSnapshotIsInvalidatedWithIt:
    def test_the_schema_version_moved(self):
        """The tokenized corpus is persisted. Changing the tokenizer without
        bumping this leaves old tokens on disk and new tokens in the query, so
        the whole identifier would match nothing — a silent no-op that looks
        like the fix landed."""
        from app.knowledge.bm25_index import _SCHEMA_VERSION

        assert _SCHEMA_VERSION >= 3

    def test_an_old_snapshot_reads_as_missing_so_the_boot_rebuild_fires(self, tmp_path):
        """`bm25_local_reconcile` skips a project when `indexed_sha` is not None,
        and `indexed_sha` goes through `load()`. A stale-schema file must
        therefore read as `None`, or the web dyno keeps an unreadable snapshot
        and the lexical leg stays dead — the F-KNOW-12 defect, reintroduced."""
        import gzip
        import json

        from app.knowledge.bm25_index import BM25Index

        index = BM25Index(tmp_path)
        path = tmp_path / "proj-x.json.gz"
        path.write_bytes(
            gzip.compress(
                json.dumps(
                    {
                        "schema_version": 2,
                        "project_id": "proj-x",
                        "indexed_sha": "deadbeef",
                        "doc_ids": ["d1:0"],
                        "doc_metadatas": [{}],
                        "raw_texts": ["x"],
                        "tokenized": [["x"]],
                    }
                ).encode()
            )
        )
        assert index.indexed_sha("proj-x") is None

    def test_the_schema_snapshots_self_heal_by_the_same_route(self):
        """The per-connection schema index shares `BM25Index`, so the version
        bump invalidates its snapshots too — and `_reconcile_schema_snapshots`
        skips a connection when `SchemaRetriever.has_index` is true. That must
        resolve through `indexed_sha`, or the schema leg goes dark on the web
        dyno with nothing to rebuild it: the same F-KNOW-12 shape, one index
        over."""
        import inspect

        from app.knowledge.schema_retriever import SchemaRetriever

        assert "indexed_sha" in inspect.getsource(SchemaRetriever.has_index)
