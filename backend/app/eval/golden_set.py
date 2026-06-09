"""Golden-set dataset for retrieval evaluation.

A golden case pairs a natural-language ``question`` with the set of document
identifiers that *should* be retrieved for it (``relevant_ids``). Identifiers
are matched against retrieved doc ids by case-insensitive substring so the set
is robust to chunk-id suffixes (e.g. ``orders.md#chunk-3`` still matches the
relevant id ``orders``).

The dataset ships as JSON (``datasets/retrieval_golden.json``) so it can be
extended without touching code and reviewed as data in PRs. Keep it small,
high-signal, and stable — it is a regression gate, not a training set.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DATASET_PATH = Path(__file__).parent / "datasets" / "retrieval_golden.json"


@dataclass(frozen=True)
class GoldenCase:
    """One labelled retrieval example."""

    id: str
    question: str
    relevant_ids: tuple[str, ...]
    # Optional grouping/notes for slicing reports (e.g. "schema" vs "codebase").
    category: str = "general"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def is_relevant(self, retrieved_id: str) -> bool:
        """True when ``retrieved_id`` matches any labelled relevant id."""
        rid = (retrieved_id or "").lower()
        return any(rel.lower() in rid for rel in self.relevant_ids)


def load_golden_set(path: str | Path | None = None) -> list[GoldenCase]:
    """Load and validate the golden set from JSON.

    Raises ``ValueError`` on a malformed dataset so CI fails loudly rather than
    silently evaluating against an empty/broken set.
    """
    p = Path(path) if path is not None else _DATASET_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"golden set at {p} must be a non-empty JSON array")

    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"golden case #{i} is not an object")
        case_id = str(item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        relevant = item.get("relevant_ids") or []
        if not case_id:
            raise ValueError(f"golden case #{i} missing 'id'")
        if case_id in seen_ids:
            raise ValueError(f"duplicate golden case id: {case_id!r}")
        if not question:
            raise ValueError(f"golden case {case_id!r} missing 'question'")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"golden case {case_id!r} must list >=1 'relevant_ids'")
        seen_ids.add(case_id)
        cases.append(
            GoldenCase(
                id=case_id,
                question=question,
                relevant_ids=tuple(str(r) for r in relevant),
                category=str(item.get("category") or "general"),
                tags=tuple(str(t) for t in (item.get("tags") or [])),
            )
        )
    logger.debug("loaded %d golden cases from %s", len(cases), p)
    return cases


__all__ = ["GoldenCase", "load_golden_set"]
