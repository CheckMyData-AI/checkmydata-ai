"""A symbol's chunk id depended on the order its file was parsed in (S5).

`code_symbol_chunker` built the id as ``sym:{path}:{uid}{suffix}:{idx}``, where
``suffix`` came from a counter kept **across every file** in the run:

    uid_occurrences: dict[str, int] = {}      # declared once, before the loop
    ...
    seen = uid_occurrences.get(symbol.uid, 0)
    uid_suffix = "" if seen == 0 else f"#{seen}"

Two consequences, and the second is the reason this changes now.

**It churns unrelated ids.** A file appearing earlier in `parsed_files` shifts
the suffix of every later duplicate uid, so editing one file can change the ids
of chunks belonging to another. The comment beside the counter says the first
occurrence keeps its historical id "so a deploy does not churn every existing
vector" — the worry was right and only half-addressed.

**It cannot be reproduced from the database.** Board row 2.2 needs the BM25
corpus to carry symbol documents under *the same* ids the vector store uses,
because `HybridRetriever._fuse` merges the legs on `doc_id` — a different id
makes one symbol two documents and **splits** its rank instead of reinforcing
it. Rebuilding that id from `code_graph_symbols` would mean replaying the parse
order, including which files were skipped because their source was unreadable,
and that skip is recorded nowhere.

So the id becomes a pure function of the symbol's own identity —
``(file_path, uid, start_line)`` — all three of which are columns on
`code_graph_symbols`.

**The uniqueness guarantee is kept.** The counter existed for a real incident:
Chroma rejects a whole batch on a duplicate id, and on 2026-08-18 production lost
nine batches of 200 chunks to one `DuplicateIDError` behind a WARNING. A
collision on all three fields should be impossible, so the fallback stays and
**logs** — a silent fallback is what would make the BM25 side diverge without
anyone noticing.
"""

from __future__ import annotations

from app.knowledge.chunk_metadata import dedupe_chunk_id, symbol_chunk_id


class TestItIsAPureFunctionOfTheSymbol:
    def test_the_same_symbol_always_gets_the_same_id(self):
        a = symbol_chunk_id(source_path="app/a.py", uid="app.a.foo", start_line=12, chunk_index=0)
        b = symbol_chunk_id(source_path="app/a.py", uid="app.a.foo", start_line=12, chunk_index=0)
        assert a == b

    def test_nothing_about_other_files_can_change_it(self):
        """The whole point: no counter, no order, no neighbours."""
        assert (
            symbol_chunk_id(source_path="app/a.py", uid="app.a.foo", start_line=12, chunk_index=0)
            == "sym:app/a.py:app.a.foo@12:0"
        )

    def test_two_symbols_sharing_a_uid_in_one_file_still_differ(self):
        """Same name, different place — which is what the global counter was
        clumsily encoding."""
        first = symbol_chunk_id(source_path="a.py", uid="dup", start_line=10, chunk_index=0)
        second = symbol_chunk_id(source_path="a.py", uid="dup", start_line=40, chunk_index=0)
        assert first != second

    def test_the_same_symbol_in_two_files_differs(self):
        assert symbol_chunk_id(
            source_path="a.py", uid="dup", start_line=10, chunk_index=0
        ) != symbol_chunk_id(source_path="b.py", uid="dup", start_line=10, chunk_index=0)

    def test_chunks_of_one_symbol_differ(self):
        assert symbol_chunk_id(
            source_path="a.py", uid="f", start_line=1, chunk_index=0
        ) != symbol_chunk_id(source_path="a.py", uid="f", start_line=1, chunk_index=1)

    def test_the_prefix_still_marks_it_as_a_symbol_chunk(self):
        """CODEIDX-C19: `sym:` keeps symbol chunk ids distinct from prose chunk
        ids, which are prefixed with the doc's database id."""
        assert symbol_chunk_id(source_path="a.py", uid="f", start_line=1, chunk_index=0).startswith(
            "sym:"
        )


class TestTheChunkerUsesIt:
    def test_it_does_not_derive_the_id_itself(self):
        """One definition, because board row 2.2 is about to build the same id
        from Postgres and a second derivation would silently disagree."""
        from pathlib import Path

        src = Path("app/knowledge/code_symbol_chunker.py").read_text(encoding="utf-8")
        assert "symbol_chunk_id(" in src
        assert 'f"sym:' not in src, "the id must not be assembled inline any more"

    def test_the_global_occurrence_counter_is_gone(self):
        from pathlib import Path

        src = Path("app/knowledge/code_symbol_chunker.py").read_text(encoding="utf-8")
        assert "uid_occurrences" not in src, (
            "a counter over every file is exactly what made the id unreproducible "
            "from the database and churnable by unrelated edits"
        )


class TestTheDuplicateGuardSurvivesAndSpeaks:
    """Chroma rejects a whole batch on a duplicate id — nine batches of 200 lost
    in one production incident. The guard stays; what changes is that it can no
    longer fire silently, because a fallback id is one the BM25 corpus cannot
    reproduce."""

    def test_a_collision_still_yields_distinct_ids(self):
        seen: dict[str, int] = {}
        first = dedupe_chunk_id("sym:a.py:f@1:0", seen)
        second = dedupe_chunk_id("sym:a.py:f@1:0", seen)
        assert first != second

    def test_the_first_occurrence_keeps_its_id_verbatim(self):
        """Otherwise every existing vector churns on deploy."""
        seen: dict[str, int] = {}
        assert dedupe_chunk_id("sym:a.py:f@1:0", seen) == "sym:a.py:f@1:0"

    def test_a_collision_is_logged(self, caplog):
        import logging

        seen: dict[str, int] = {}
        dedupe_chunk_id("sym:a.py:f@1:0", seen)
        with caplog.at_level(logging.WARNING):
            dedupe_chunk_id("sym:a.py:f@1:0", seen)
        assert any("collision" in r.message.lower() for r in caplog.records), (
            "a silent fallback produces an id the BM25 corpus cannot reproduce, "
            "and the divergence would be invisible"
        )
