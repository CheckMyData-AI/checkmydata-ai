"""Tests for context_pack_renderer — RET-R3: greedy relevance×confidence packing.

Covers:
- Over-budget pack is trimmed to fit token_budget["total"] by priority score
- Trimmed artifacts are noted in pack.token_budget["omitted_count"] + note
- Under-budget pack keeps all artifacts unchanged
- Priority score = relevance × confidence; higher scores win
- Section minimum reservation: tables/rules always keep ≥1 if present
- Deterministic (no model — uses fallback WindowTokenizer)
- Injecting custom token-size function for hermetic testing
"""

from __future__ import annotations

from collections.abc import Callable

from app.knowledge.context_pack import Artifact, ContextPack
from app.knowledge.context_pack_renderer import pack_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _art(
    art_id: str,
    *,
    art_type: str = "rag_chunk",
    title: str = "t",
    summary: str = "x",
    confidence: float = 1.0,
    relevance: float = 1.0,
    tokens: int = 100,
) -> Artifact:
    """Factory for deterministic Artifact instances used in tests."""
    a = Artifact(
        id=art_id,
        type=art_type,
        title=title,
        summary=summary,
        confidence=confidence,
        payload={"relevance": relevance, "_test_tokens": tokens},
    )
    return a


def _token_sizer(token_map: dict[str, int]) -> Callable[[Artifact], int]:
    """Return a token-size function that looks up by artifact id."""

    def _size(a: Artifact) -> int:
        return token_map.get(a.id, a.payload.get("_test_tokens", 100))

    return _size


# ---------------------------------------------------------------------------
# Under-budget — keep everything
# ---------------------------------------------------------------------------


class TestUnderBudgetKeepsAll:
    def test_all_artifacts_kept_when_under_budget(self) -> None:
        arts = [
            _art("a1", tokens=50),
            _art("a2", tokens=50),
            _art("a3", tokens=50),
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 1000},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert result.omitted_count == 0
        assert len(result.pack.rag_chunks) == 3

    def test_omission_note_absent_when_nothing_dropped(self) -> None:
        pack = ContextPack(
            project_id="p",
            rag_chunks=[_art("a1", tokens=10)],
            token_budget={"total": 500},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert result.omission_note == ""
        assert result.pack.token_budget.get("omitted_count", 0) == 0

    def test_empty_pack_under_budget_stays_empty(self) -> None:
        pack = ContextPack(project_id="p", token_budget={"total": 500})
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert result.omitted_count == 0
        assert result.pack.is_empty()


# ---------------------------------------------------------------------------
# Over-budget — trim by priority
# ---------------------------------------------------------------------------


class TestOverBudgetTrims:
    def test_over_budget_drops_lowest_priority_artifacts(self) -> None:
        """Budget = 200 tokens; each artifact is 100 tokens → keep top-2."""
        arts = [
            _art("high", confidence=0.9, relevance=0.9, tokens=100),  # score=0.81
            _art("mid", confidence=0.7, relevance=0.7, tokens=100),  # score=0.49
            _art("low", confidence=0.3, relevance=0.3, tokens=100),  # score=0.09
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 200},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        kept_ids = {a.id for a in result.pack.rag_chunks}
        assert "high" in kept_ids
        assert "mid" in kept_ids
        assert "low" not in kept_ids
        assert result.omitted_count == 1

    def test_omission_note_mentions_count(self) -> None:
        arts = [_art(f"a{i}", tokens=100) for i in range(5)]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 200},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert result.omission_note != ""
        assert "3" in result.omission_note  # 5 total - 2 fit = 3 omitted

    def test_token_budget_reflects_omitted_count(self) -> None:
        arts = [_art(f"a{i}", tokens=100) for i in range(4)]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 200},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert result.pack.token_budget["omitted_count"] == 2

    def test_priority_order_highest_confidence_wins(self) -> None:
        """When relevance is equal, higher confidence should be kept."""
        arts = [
            _art("best", confidence=1.0, relevance=1.0, tokens=100),
            _art("worst", confidence=0.1, relevance=1.0, tokens=100),
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 100},  # room for exactly 1
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert len(result.pack.rag_chunks) == 1
        assert result.pack.rag_chunks[0].id == "best"

    def test_multi_section_trim_across_sections(self) -> None:
        """Over-budget pack spanning tables + learnings; top priorities kept."""
        tables = [
            _art("t1", art_type="table", confidence=0.9, relevance=1.0, tokens=100),
        ]
        learnings = [
            _art("l1", art_type="learning", confidence=0.5, relevance=0.5, tokens=100),
            _art("l2", art_type="learning", confidence=0.2, relevance=0.2, tokens=100),
        ]
        pack = ContextPack(
            project_id="p",
            tables=tables,
            learnings=learnings,
            token_budget={"total": 150},  # fits 1 full artifact at 100 tokens
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        all_kept = result.pack.all_artifacts()
        kept_ids = {a.id for a in all_kept}
        # t1 has score 0.9; l1 has 0.25; l2 has 0.04 → t1 wins
        assert "t1" in kept_ids
        assert result.omitted_count >= 1


# ---------------------------------------------------------------------------
# Section minimum reservation
# ---------------------------------------------------------------------------


class TestSectionMinimums:
    def test_tables_get_at_least_one_when_present(self) -> None:
        """Even with a very tight budget, at least one table artifact is kept."""
        tables = [_art("tbl1", art_type="table", confidence=0.1, relevance=0.1, tokens=100)]
        # Add many high-priority rag_chunks that would otherwise crowd out tables
        rag = [_art(f"r{i}", confidence=1.0, relevance=1.0, tokens=100) for i in range(10)]
        pack = ContextPack(
            project_id="p",
            tables=tables,
            rag_chunks=rag,
            token_budget={"total": 200},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert any(a.id == "tbl1" for a in result.pack.tables), (
            "At least one table must be reserved even when its priority is lowest"
        )

    def test_rules_get_at_least_one_when_present(self) -> None:
        """At least one rule artifact is always kept when rules are present."""
        rules = [_art("rule1", art_type="rule", confidence=0.05, relevance=0.05, tokens=100)]
        rag = [_art(f"r{i}", confidence=1.0, relevance=1.0, tokens=100) for i in range(10)]
        pack = ContextPack(
            project_id="p",
            rules=rules,
            rag_chunks=rag,
            token_budget={"total": 200},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert any(a.id == "rule1" for a in result.pack.rules), (
            "At least one rule must be reserved even when its priority is lowest"
        )


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


class TestTokenBudgetEnforcement:
    def test_total_tokens_never_exceeds_budget(self) -> None:
        """Total tokens of kept artifacts must not exceed token_budget['total']."""
        sizes = {f"a{i}": (i + 1) * 30 for i in range(10)}  # 30..300 tokens each
        arts = [
            _art(f"a{i}", confidence=float(10 - i) / 10, relevance=1.0, tokens=sizes[f"a{i}"])
            for i in range(10)
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 300},
        )
        result = pack_context(pack, token_size_fn=_token_sizer(sizes))
        total = sum(sizes[a.id] for a in result.pack.rag_chunks)
        assert total <= 300, f"Token total {total} exceeds budget 300"

    def test_no_budget_key_keeps_all(self) -> None:
        """When token_budget is empty/missing, keep all artifacts (no enforcement)."""
        arts = [_art(f"a{i}", tokens=1000) for i in range(5)]
        pack = ContextPack(project_id="p", rag_chunks=arts, token_budget={})
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert len(result.pack.rag_chunks) == 5
        assert result.omitted_count == 0

    def test_zero_budget_keeps_section_minimums_only(self) -> None:
        """Budget=0 with tables present → tables minimum reservation applies."""
        tables = [_art("tbl1", art_type="table", tokens=100)]
        rag = [_art("r1", tokens=100)]
        pack = ContextPack(
            project_id="p",
            tables=tables,
            rag_chunks=rag,
            token_budget={"total": 0},
        )
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        # Table minimum means tbl1 is reserved even at budget=0
        assert any(a.id == "tbl1" for a in result.pack.tables)


# ---------------------------------------------------------------------------
# PackingResult contract
# ---------------------------------------------------------------------------


class TestPackingResult:
    def test_result_has_original_pack_reference(self) -> None:
        pack = ContextPack(project_id="p", token_budget={"total": 1000})
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        # result.pack may be the same or a new instance; either is fine
        assert result.pack is not None
        assert result.pack.project_id == "p"

    def test_result_omitted_count_int(self) -> None:
        pack = ContextPack(project_id="p", token_budget={"total": 1000})
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert isinstance(result.omitted_count, int)

    def test_result_tokens_used_int(self) -> None:
        pack = ContextPack(project_id="p", token_budget={"total": 1000})
        result = pack_context(pack, token_size_fn=_token_sizer({}))
        assert isinstance(result.tokens_used, int)

    def test_tokens_used_equals_sum_of_kept(self) -> None:
        sizes = {"a1": 80, "a2": 70, "a3": 60}
        arts = [_art(a_id, tokens=sizes[a_id]) for a_id in ("a1", "a2", "a3")]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 500},
        )
        result = pack_context(pack, token_size_fn=_token_sizer(sizes))
        expected = sum(sizes[a.id] for a in result.pack.rag_chunks)
        assert result.tokens_used == expected


# ---------------------------------------------------------------------------
# Default tokenizer path (no injection — uses WindowTokenizer fallback)
# ---------------------------------------------------------------------------


class TestDefaultTokenizerPath:
    def test_pack_without_injection_uses_windowtokenizer(self) -> None:
        """pack_context with no token_size_fn must not raise; uses fallback tokenizer."""
        arts = [
            Artifact(
                id="a1",
                type="rag_chunk",
                title="title",
                summary="Some text that should be counted conservatively.",
                confidence=1.0,
            ),
            Artifact(
                id="a2",
                type="rag_chunk",
                title="title2",
                summary="Another piece of text.",
                confidence=0.5,
            ),
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 10_000},
        )
        result = pack_context(pack)
        # Both fit easily in 10_000 tokens
        assert result.omitted_count == 0
        assert len(result.pack.rag_chunks) == 2

    def test_tight_budget_default_tokenizer_drops_artifacts(self) -> None:
        """Very tight budget forces at least one drop even with default tokenizer."""
        arts = [
            Artifact(
                id=f"a{i}",
                type="rag_chunk",
                title=f"title{i}",
                summary="w " * 500,  # ~500 words → definitely > 10 tokens
                confidence=float(10 - i) / 10,
            )
            for i in range(5)
        ]
        pack = ContextPack(
            project_id="p",
            rag_chunks=arts,
            token_budget={"total": 10},  # impossibly tight
        )
        result = pack_context(pack)
        assert result.omitted_count > 0
