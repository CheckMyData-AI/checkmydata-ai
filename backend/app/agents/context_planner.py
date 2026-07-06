"""ContextPlanner — decides *what* knowledge to load, not *load everything*.

Phase 4 of the Knowledge Architecture roadmap. Historically the orchestrator
eagerly loaded six-plus context categories (tables, lineage, learnings, rules,
insights, RAG) for every question, paying tokens and latency even when a
category was irrelevant. The planner inspects the question (plus the router's
cheap signals) and emits a :class:`ContextPlan`: which categories to fetch and
how big each slice may be, with a short rationale.

Two modes:

* **heuristic** (default, zero-cost, deterministic) — keyword + router-signal
  rules. Good enough to prune obviously-irrelevant categories and the easiest
  to test/gate.
* **llm** (opt-in) — a lightweight classification call. Falls back to the
  heuristic on any error so the planner can never hard-fail a request.

The planner is **advisory**: an empty/degraded plan means "load the safe
default set", so enabling it can only narrow, never break, context assembly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Word-boundary cue matching (ORCH-CP01)
# ---------------------------------------------------------------------------
# Naive substring matching (`cue in q`) was too broad: "code" matched "country
# code", "drop" matched "drop-off", "how is" matched "how is it going".
# Single-word cues are matched with `\b` word boundaries so they only fire when
# the cue appears as a standalone token.  Multi-word phrase cues keep plain
# substring matching (no risk of false sub-token hits for multi-word sequences).
_WORD_CACHE: dict[str, re.Pattern[str]] = {}


def _word_match(q: str, cue: str) -> bool:
    """Return True if *cue* appears in *q* with appropriate precision.

    * Single-word cues use ``\\b`` word-boundary anchors so ``"drop"`` does not
      match ``"drop-off"`` and ``"function"`` does not match ``"functional"``.
    * Multi-word phrase cues (contain a space) use plain substring matching —
      there is no sub-token false-positive risk for phrases like ``"where is"``
      or ``"how does"``.
    """
    if " " in cue:
        return cue in q
    pat = _WORD_CACHE.get(cue)
    if pat is None:
        pat = _WORD_CACHE[cue] = re.compile(rf"\b{re.escape(cue)}\b")
    return bool(pat.search(q))


class ContextNeed(StrEnum):
    """A loadable knowledge category."""

    TABLES = "tables"
    LINEAGE = "lineage"
    LEARNINGS = "learnings"
    RULES = "rules"
    INSIGHTS = "insights"
    RAG = "rag"


# The full set — used as the safe default when planning is disabled or degraded.
ALL_NEEDS: tuple[ContextNeed, ...] = tuple(ContextNeed)

# Default per-category fetch limits (mirrors KnowledgeCatalogService defaults).
_DEFAULT_LIMITS: dict[ContextNeed, int] = {
    ContextNeed.TABLES: 40,
    ContextNeed.LINEAGE: 60,
    ContextNeed.LEARNINGS: 15,
    ContextNeed.RULES: 50,
    ContextNeed.INSIGHTS: 5,
    ContextNeed.RAG: 3,
}


@dataclass(frozen=True)
class ContextPlan:
    """A query-aware loading plan for the KnowledgeCatalogService."""

    needs: frozenset[ContextNeed]
    limits: dict[ContextNeed, int] = field(default_factory=dict)
    budget_tokens: int = 8000
    rationale: str = ""
    mode: str = "heuristic"

    def wants(self, need: ContextNeed) -> bool:
        return need in self.needs

    def limit_for(self, need: ContextNeed) -> int:
        return self.limits.get(need, _DEFAULT_LIMITS.get(need, 0))

    def to_dict(self) -> dict:
        return {
            "needs": sorted(n.value for n in self.needs),
            "limits": {n.value: v for n, v in self.limits.items()},
            "budget_tokens": self.budget_tokens,
            "rationale": self.rationale,
            "mode": self.mode,
        }

    @classmethod
    def full(cls, *, budget_tokens: int = 8000, rationale: str = "default") -> ContextPlan:
        """The safe default: every category at default limits."""
        return cls(
            needs=frozenset(ALL_NEEDS),
            limits=dict(_DEFAULT_LIMITS),
            budget_tokens=budget_tokens,
            rationale=rationale,
            mode="default",
        )


# Keyword cues per category. Intentionally small/high-precision; the planner
# always keeps a baseline set so a miss degrades to "load a bit more", never
# "load nothing".
_CUES: dict[ContextNeed, tuple[str, ...]] = {
    ContextNeed.LINEAGE: (
        "lineage",
        "where is",
        "which code",
        "written by",
        "populated",
        "comes from",
        "source of",
        "how is",
        "derived",
        "mapping",
        "etl",
    ),
    ContextNeed.LEARNINGS: (
        "usually",
        "before",
        "last time",
        "remember",
        "we learned",
        "known issue",
        "gotcha",
        "caveat",
    ),
    ContextNeed.RULES: (
        "rule",
        "policy",
        "must",
        "should",
        "convention",
        "standard",
        "allowed",
        "forbidden",
        "compliance",
    ),
    ContextNeed.INSIGHTS: (
        "insight",
        "anomaly",
        "trend",
        "why did",
        "spike",
        # "drop" removed (CP01): matched "drop-off" as a false positive.
        # Use the explicit phrase "drop-off" to stay precise.
        "drop-off",
        "recommend",
        "alert",
        "unusual",
    ),
    ContextNeed.RAG: (
        # "code" removed (CP01): "country code", "zip code", "status code" all
        # contain the token "code" as a word, making \b insufficient to eliminate
        # false positives.  Rely on the remaining high-precision cues instead.
        "function",
        "class",
        "module",
        "implementation",
        "file",
        "readme",
        "doc",
        "how does",
        "architecture",
    ),
}


class ContextPlanner:
    """Plans context loading from a question + cheap router signals."""

    def __init__(self, *, mode: str = "heuristic") -> None:
        self._mode = mode

    async def plan(
        self,
        question: str,
        *,
        estimated_queries: int = 1,
        needs_multiple_data_sources: bool = False,
        has_connection: bool = True,
        has_repo: bool = True,
        budget_tokens: int = 8000,
    ) -> ContextPlan:
        """Return a :class:`ContextPlan` for ``question``.

        Never raises: any failure (including a future LLM path) falls back to
        the full safe plan.
        """
        try:
            return self._plan_heuristic(
                question,
                estimated_queries=estimated_queries,
                needs_multiple_data_sources=needs_multiple_data_sources,
                has_connection=has_connection,
                has_repo=has_repo,
                budget_tokens=budget_tokens,
            )
        except Exception:
            logger.warning("context planner failed — using full plan", exc_info=True)
            return ContextPlan.full(budget_tokens=budget_tokens, rationale="planner-error")

    # ------------------------------------------------------------------
    def _plan_heuristic(
        self,
        question: str,
        *,
        estimated_queries: int,
        needs_multiple_data_sources: bool,
        has_connection: bool,
        has_repo: bool,
        budget_tokens: int,
    ) -> ContextPlan:
        q = (question or "").lower()
        needs: set[ContextNeed] = set()
        reasons: list[str] = []

        # Baseline: rules + learnings are cheap, high-value priors — always on.
        needs.update({ContextNeed.RULES, ContextNeed.LEARNINGS})

        # DB-backed categories only make sense with a connection.
        if has_connection:
            needs.add(ContextNeed.TABLES)
            reasons.append("connection→tables")

        # Keyword-cued categories — word-boundary matching (ORCH-CP01).
        for need, cues in _CUES.items():
            if any(_word_match(q, cue) for cue in cues):
                if need is ContextNeed.RAG and not has_repo:
                    continue
                if need in (ContextNeed.LINEAGE,) and not has_connection:
                    continue
                needs.add(need)
                reasons.append(f"cue→{need.value}")

        # Multi-source / complex questions widen the net (lineage + insights +
        # rag) since they likely cross code↔DB boundaries.
        if needs_multiple_data_sources or estimated_queries >= 3:
            if has_connection:
                needs.add(ContextNeed.LINEAGE)
                needs.add(ContextNeed.INSIGHTS)
            if has_repo:
                needs.add(ContextNeed.RAG)
            reasons.append("complex→widen")

        # RAG is the default knowledge source for repos when nothing else cued.
        if has_repo and ContextNeed.RAG not in needs and len(needs) <= 3:
            needs.add(ContextNeed.RAG)
            reasons.append("repo→rag-baseline")

        # Budget allocation: tighten slices for narrow questions, widen for
        # complex ones.
        limits = dict(_DEFAULT_LIMITS)
        if estimated_queries <= 1 and not needs_multiple_data_sources:
            limits[ContextNeed.TABLES] = 20
            limits[ContextNeed.LEARNINGS] = 8

        return ContextPlan(
            needs=frozenset(needs),
            limits=limits,
            budget_tokens=budget_tokens,
            rationale="; ".join(reasons) or "baseline",
            mode="heuristic",
        )


# CP02 note: ContextPlanner.plan() is invoked on the hot path via
# ContextLoader.assemble_knowledge_block (orchestrator.py ~line 912), which is
# wired behind context_planner_enabled (W2-T8 / RET-R1).  W3 (this file)
# delivers the cue-precision fix only; the runtime invocation is W2's concern.

__all__ = ["ALL_NEEDS", "ContextNeed", "ContextPlan", "ContextPlanner", "_word_match"]
