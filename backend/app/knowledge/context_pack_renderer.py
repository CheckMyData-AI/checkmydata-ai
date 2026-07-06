"""RET-R3: Greedy relevance×confidence token-budget packing for ContextPack.

This module is **pure** (no I/O, no DB, no config import) so it is fully
unit-testable and does not collide with W3 orchestrator edits.

Algorithm
---------
1. Derive a **priority score** for each artifact:
   ``priority = relevance(artifact) × artifact.confidence``

   *relevance* extraction:
   - ``artifact.payload["relevance"]`` if present (injected by tests / future callers).
   - ``artifact.payload["rrf_score"]`` if present (HybridRetriever fused score).
   - Otherwise 1.0 (safe default — confidence alone drives the ordering).

2. Apply **section minimums**: one artifact from ``tables`` and one from
   ``rules`` are pre-reserved (greedy fill begins *after* these slots) so a
   wide question never starves those critical sections entirely.

3. **Greedy fill**: sort remaining candidates by descending priority; iterate
   and add while ``tokens_used + artifact_tokens <= budget``.

4. **Omission note**: if any artifacts are dropped, record ``omitted_count``
   and a human-readable note in ``pack.token_budget``.

When ``token_budget["total"]`` is absent or zero, section minimums still apply
but no token gate is enforced (budget=0 is treated as "reserve minimums only,
drop the rest").

Usage
-----
>>> from app.knowledge.context_pack_renderer import pack_context
>>> result = pack_context(pack)           # uses WindowTokenizer fallback
>>> result = pack_context(pack, token_size_fn=my_sizer)  # inject for tests
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.knowledge.context_pack import Artifact, ContextPack

logger = logging.getLogger(__name__)

# Names of sections that always get at least one artifact reserved.
_RESERVED_SECTIONS: tuple[str, ...] = ("tables", "rules")

# Default model for the fallback WindowTokenizer.
_DEFAULT_TOKENIZER_MODEL = "BAAI/bge-base-en-v1.5"


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class PackingResult:
    """Outcome of :func:`pack_context`.

    Attributes
    ----------
    pack:
        A *new* ``ContextPack`` whose section lists contain only the kept
        artifacts (all other fields — freshness, sources_used, plan, etc. —
        are shallow-copied from the original).
    omitted_count:
        Number of artifacts dropped to fit the budget.
    tokens_used:
        Sum of token counts for kept artifacts.
    omission_note:
        Human-readable omission message, or ``""`` when nothing was dropped.
    """

    pack: ContextPack
    omitted_count: int = 0
    tokens_used: int = 0
    omission_note: str = ""


# ---------------------------------------------------------------------------
# Priority helper
# ---------------------------------------------------------------------------


def _relevance(artifact: Artifact) -> float:
    """Extract the relevance signal from an artifact's payload.

    Precedence:
    1. ``payload["relevance"]``   — explicit injection (tests / future use).
    2. ``payload["rrf_score"]``   — HybridRetriever fused RRF score.
    3. 1.0                        — default (confidence alone drives order).
    """
    payload = artifact.payload
    if "relevance" in payload:
        try:
            return float(payload["relevance"])
        except (TypeError, ValueError):
            pass
    if "rrf_score" in payload:
        try:
            return float(payload["rrf_score"])
        except (TypeError, ValueError):
            pass
    return 1.0


def _priority(artifact: Artifact) -> float:
    """Priority score = relevance × confidence.  Always in [0, 1]."""
    raw = _relevance(artifact) * artifact.confidence
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Token-size helper
# ---------------------------------------------------------------------------


def _make_default_sizer() -> Callable[[Artifact], int]:
    """Build a token-size function using :class:`WindowTokenizer` (lazy + fallback).

    The WindowTokenizer degrades silently to ``ceil(len(text)/3)`` when the
    real model can't be loaded — no network required, no exception propagation.
    """
    from app.knowledge.tokenizer_window import get_tokenizer

    tok = get_tokenizer(_DEFAULT_TOKENIZER_MODEL)

    def _size(artifact: Artifact) -> int:
        # Estimate tokens from title + summary (the fields exposed to the LLM).
        text = f"{artifact.title}\n{artifact.summary}"
        return tok.count_tokens(text)

    return _size


# ---------------------------------------------------------------------------
# Core packer
# ---------------------------------------------------------------------------


def pack_context(
    pack: ContextPack,
    *,
    token_size_fn: Callable[[Artifact], int] | None = None,
) -> PackingResult:
    """Greedily fill a token budget by priority score across all pack sections.

    Parameters
    ----------
    pack:
        Source ``ContextPack`` (not mutated — a new pack is returned).
    token_size_fn:
        Optional callable ``(Artifact) -> int`` returning the token count for
        a single artifact.  Defaults to :func:`_make_default_sizer` (uses
        WindowTokenizer with char-based fallback).

    Returns
    -------
    PackingResult
        Trimmed pack, omitted count, tokens used, and omission note.
    """
    sizer = token_size_fn if token_size_fn is not None else _make_default_sizer()

    budget_total: int | None = None
    raw = pack.token_budget.get("total") if pack.token_budget else None
    if raw is not None:
        try:
            budget_total = int(raw)
        except (TypeError, ValueError):
            budget_total = None

    # No budget → keep everything, skip all packing logic.
    if budget_total is None:
        result_pack = _shallow_copy_pack(pack)
        return PackingResult(pack=result_pack, tokens_used=_total_tokens(pack, sizer))

    # Gather all artifacts with their pre-computed sizes + priorities.
    all_arts: list[tuple[str, Artifact, int, float]] = []  # (section, art, tokens, priority)
    for section_name in ("tables", "lineage", "learnings", "rules", "insights", "rag_chunks"):
        for art in getattr(pack, section_name):
            tok_count = sizer(art)
            all_arts.append((section_name, art, tok_count, _priority(art)))

    total_available = len(all_arts)

    # --- Phase 1: reserve section minimums -----------------------------------
    reserved: dict[str, list[tuple[str, Artifact, int, float]]] = {}
    for section_name in _RESERVED_SECTIONS:
        section_arts = [(s, a, t, p) for (s, a, t, p) in all_arts if s == section_name]
        if section_arts:
            # Pick the highest-priority one as the reserved slot.
            best = max(section_arts, key=lambda x: x[3])
            reserved[section_name] = [best]

    reserved_set: set[str] = {a.id for group in reserved.values() for (_, a, _, _) in group}
    reserved_tokens = sum(t for group in reserved.values() for (_, _, t, _) in group)

    # --- Phase 2: greedy fill from remaining ---------------------------------
    remaining = [x for x in all_arts if x[1].id not in reserved_set]
    remaining.sort(key=lambda x: x[3], reverse=True)

    tokens_used = reserved_tokens
    greedy_kept: list[tuple[str, Artifact, int, float]] = []

    for entry in remaining:
        _, art, tok_count, _ = entry
        if budget_total > 0 and tokens_used + tok_count > budget_total:
            continue  # skip — over budget
        tokens_used += tok_count
        greedy_kept.append(entry)

    # --- Phase 3: assemble kept set ------------------------------------------
    kept_ids: set[str] = reserved_set | {a.id for (_, a, _, _) in greedy_kept}
    omitted_count = total_available - len(kept_ids)

    # Build per-section kept lists (preserve original ordering within sections).
    section_kept: dict[str, list[Artifact]] = {
        s: [] for s in ("tables", "lineage", "learnings", "rules", "insights", "rag_chunks")
    }
    for section_name in section_kept:
        for art in getattr(pack, section_name):
            if art.id in kept_ids:
                section_kept[section_name].append(art)

    # Rebuild token_budget with omission metadata.
    new_budget = dict(pack.token_budget)
    new_budget["omitted_count"] = omitted_count

    omission_note = ""
    if omitted_count > 0:
        omission_note = (
            f"{omitted_count} artifact{'s' if omitted_count != 1 else ''} omitted (budget)"
        )
        new_budget["omission_note"] = omission_note

    result_pack = ContextPack(
        project_id=pack.project_id,
        connection_id=pack.connection_id,
        question=pack.question,
        tables=section_kept["tables"],
        lineage=section_kept["lineage"],
        learnings=section_kept["learnings"],
        rules=section_kept["rules"],
        insights=section_kept["insights"],
        rag_chunks=section_kept["rag_chunks"],
        freshness=pack.freshness,
        sources_used=list(pack.sources_used),
        token_budget=new_budget,
        plan=pack.plan,
    )

    logger.debug(
        "context_pack_renderer: budget=%d kept=%d omitted=%d tokens_used=%d",
        budget_total,
        len(kept_ids),
        omitted_count,
        tokens_used,
    )

    return PackingResult(
        pack=result_pack,
        omitted_count=omitted_count,
        tokens_used=tokens_used,
        omission_note=omission_note,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _shallow_copy_pack(pack: ContextPack) -> ContextPack:
    """Return a new ContextPack with identical section lists (shallow copy)."""
    return ContextPack(
        project_id=pack.project_id,
        connection_id=pack.connection_id,
        question=pack.question,
        tables=list(pack.tables),
        lineage=list(pack.lineage),
        learnings=list(pack.learnings),
        rules=list(pack.rules),
        insights=list(pack.insights),
        rag_chunks=list(pack.rag_chunks),
        freshness=pack.freshness,
        sources_used=list(pack.sources_used),
        token_budget=dict(pack.token_budget),
        plan=pack.plan,
    )


def _total_tokens(pack: ContextPack, sizer: Callable[[Artifact], int]) -> int:
    """Sum token counts for all artifacts in a pack."""
    return sum(sizer(a) for a in pack.all_artifacts())


# ---------------------------------------------------------------------------
# RET-R8: per-artifact provenance rendering
# ---------------------------------------------------------------------------

_TRACEABLE_HEADER = "RELEVANT KNOWLEDGE (traceable):"


def render_context_block(artifacts: list[Artifact]) -> str:
    """Render a prompt block with per-artifact provenance annotations (RET-R8).

    Returns ``""`` for an empty artifact list.  Each line follows the C-E format::

        - [{source} @ {commit_sha} · {indexed_at} · conf={confidence:.2f}] {summary}

    ``commit_sha`` falls back to ``"—"`` when absent; ``indexed_at`` falls
    back to ``"—"`` when absent.  The function never raises on missing fields.

    Parameters
    ----------
    artifacts:
        Flat list of :class:`~app.knowledge.context_pack.Artifact` instances
        (typically from :meth:`~app.knowledge.context_pack.ContextPack.all_artifacts`
        or a filtered subset after packing).

    Returns
    -------
    str
        Multi-line prompt block starting with the traceable header, or ``""``
        when *artifacts* is empty.
    """
    if not artifacts:
        return ""

    lines: list[str] = [_TRACEABLE_HEADER]
    # RET-R15: dedup on identical summaries so symbol chunks and prose chunks
    # that describe the same entity don't produce duplicate lines.  First
    # occurrence wins (earlier artifacts tend to be higher confidence).
    seen_summaries: set[str] = set()
    for a in artifacts:
        if a.summary in seen_summaries:
            continue
        seen_summaries.add(a.summary)
        src = a.provenance.get("source", "unknown") if a.provenance else "unknown"
        sha = (a.provenance.get("commit_sha") or "—") if a.provenance else "—"
        iat = (a.freshness.get("indexed_at") or "—") if a.freshness else "—"
        lines.append(f"- [{src} @ {sha} · {iat} · conf={a.confidence:.2f}] {a.summary}")
    return "\n".join(lines)


__all__ = ["PackingResult", "pack_context", "render_context_block"]
