"""T00-mem: the BM25 snapshot does not keep what only the file needs.

Measured on the production corpus (32 571 documents, 2026-09-17): the tokenized
corpus was **58.9 MB** in the web process — the largest single object, against
55.6 MB for the BM25 structures and 9.2 MB for the document texts — and nothing read
it after `BM25Okapi` was built. A web dyno that needed 525 MB to answer one question
on a 512 MB quota was carrying a copy for the file writer.
"""

from __future__ import annotations

import dataclasses
import gzip
import json

from app.knowledge.bm25_index import BM25Index, BM25Snapshot


def _docs(n: int = 5) -> list[tuple[str, str, dict]]:
    # Distinct words per document: a term every document shares has an idf of zero
    # and scores nothing, which is BM25 working, not the index failing.
    words = ["purchases", "refunds", "sessions", "invoices", "shipments"]
    return [(f"d{i}", f"select count(*) from {words[i % len(words)]}", {"k": i}) for i in range(n)]


def test_the_snapshot_holds_no_tokenized_corpus(tmp_path):
    index = BM25Index(tmp_path)
    snap = index.build("proj", "sha", _docs())

    assert not hasattr(snap, "tokenized"), (
        "the tokens are what the FILE needs; keeping them doubles the corpus in memory"
    )
    fields = {f.name for f in dataclasses.fields(BM25Snapshot)}
    assert "tokenized" not in fields


def test_the_file_still_carries_the_tokens_and_a_reload_scores_the_same(tmp_path):
    index = BM25Index(tmp_path)
    built = index.build("proj", "sha", _docs())
    hits_before, reason_before = index.query_with_reason("proj", "refunds", n_results=3)

    with gzip.open(tmp_path / "proj.json.gz", "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["tokenized"], "the corpus is still inspectable with zcat"
    assert len(payload["tokenized"]) == len(built.doc_ids)

    index._snapshots.clear()  # force a read from disk
    hits_after, reason_after = index.query_with_reason("proj", "refunds", n_results=3)

    assert (reason_before, reason_after) == ("ok", "ok")
    assert [h["id"] for h in hits_before] == [h["id"] for h in hits_after]
    assert [round(h["score"], 6) for h in hits_before] == [round(h["score"], 6) for h in hits_after]
    assert hits_after[0]["document"], "a hit still carries its text"
