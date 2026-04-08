"""Lightweight heuristic table resolver.

Parses a compact table-map string (``name(~rows, desc), ...``) and matches
user questions against known tables via exact, fuzzy, and keyword-to-description
strategies.  Runs in <1 ms — no LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TABLE_MAP_RE = re.compile(r"(\w+)\(([^)]*)\)")


@dataclass(frozen=True, slots=True)
class TableResolution:
    """Result of resolving a user question against the known table map."""

    matched: list[str] = field(default_factory=list)
    fuzzy: list[tuple[str, str, float]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def parse_table_map(table_map: str) -> dict[str, str]:
    """Parse ``name(~rows, description), ...`` into ``{name: description}``."""
    result: dict[str, str] = {}
    for m in _TABLE_MAP_RE.finditer(table_map):
        name = m.group(1)
        meta = m.group(2)
        parts = meta.split(",", 1)
        desc = parts[1].strip() if len(parts) > 1 else ""
        result[name.lower()] = desc.lower()
    return result


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase alpha-numeric tokens (≥2 chars)."""
    return {t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) >= 2}


def _token_overlap(a: str, b: str) -> float:
    """Jaccard-style overlap between two strings split into tokens."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_NOISE_WORDS = frozenset(
    {
        "show",
        "me",
        "get",
        "find",
        "all",
        "the",
        "from",
        "in",
        "of",
        "for",
        "and",
        "or",
        "with",
        "by",
        "to",
        "is",
        "are",
        "what",
        "how",
        "many",
        "much",
        "which",
        "where",
        "when",
        "who",
        "top",
        "total",
        "count",
        "sum",
        "average",
        "avg",
        "last",
        "first",
        "per",
        "each",
        "give",
        "list",
        "number",
        "data",
        "select",
        "please",
        "can",
        "you",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "was",
        "were",
        "will",
        "would",
        "should",
        "could",
        "than",
        "then",
        "that",
        "this",
        "those",
        "these",
        "not",
        "but",
        "only",
        "also",
        "been",
        "being",
        "more",
        "most",
        "less",
        "about",
        "between",
        "during",
        "after",
        "before",
        "since",
        "through",
        "into",
        "over",
        "under",
        "above",
        "below",
        "up",
        "down",
        "out",
        "on",
        "off",
        "at",
        "as",
        "an",
        "if",
        "so",
        "no",
        "yes",
        "it",
        "its",
        "my",
        "our",
        "your",
        "their",
    }
)


def _extract_candidate_terms(question: str) -> list[str]:
    """Extract meaningful candidate terms from a user question."""
    tokens = re.findall(r"[a-z][a-z0-9_]*", question.lower())
    return [t for t in tokens if t not in _NOISE_WORDS and len(t) >= 3]


def _plurals(term: str) -> set[str]:
    """Generate simple singular/plural variants."""
    variants = {term}
    if term.endswith("s"):
        variants.add(term[:-1])
        if term.endswith("ies"):
            variants.add(term[:-3] + "y")
        elif term.endswith("ses") or term.endswith("xes"):
            variants.add(term[:-2])
    else:
        variants.add(term + "s")
        if term.endswith("y"):
            variants.add(term[:-1] + "ies")
    return variants


_FUZZY_THRESHOLD = 0.30


def resolve_tables(question: str, table_map: str) -> TableResolution:
    """Match a user question against known tables.

    Returns a :class:`TableResolution` with:
    - ``matched``: table names matched exactly or via plural/singular variants
    - ``fuzzy``: ``(candidate_term, closest_table, score)`` for near-misses
    - ``unresolved``: candidate terms that matched nothing
    """
    if not table_map or not question:
        return TableResolution()

    tables = parse_table_map(table_map)
    if not tables:
        return TableResolution()

    table_names = set(tables.keys())
    candidates = _extract_candidate_terms(question)
    if not candidates:
        return TableResolution()

    matched: list[str] = []
    fuzzy: list[tuple[str, str, float]] = []
    unresolved: list[str] = []
    seen_tables: set[str] = set()
    resolved_terms: set[str] = set()

    for cand in candidates:
        variants = _plurals(cand)
        for v in variants:
            if v in table_names and v not in seen_tables:
                matched.append(v)
                seen_tables.add(v)
                resolved_terms.add(cand)
                break
            for tn in table_names:
                if v in tn or tn in v:
                    if tn not in seen_tables:
                        matched.append(tn)
                        seen_tables.add(tn)
                        resolved_terms.add(cand)
                    break

    remaining = [c for c in candidates if c not in resolved_terms]
    for cand in remaining:
        best_table = ""
        best_score = 0.0
        for tn, desc in tables.items():
            score = _token_overlap(cand, desc)
            name_score = _token_overlap(cand, tn)
            combined = max(score, name_score)
            if combined > best_score:
                best_score = combined
                best_table = tn
        if best_score >= _FUZZY_THRESHOLD and best_table not in seen_tables:
            fuzzy.append((cand, best_table, round(best_score, 2)))
            seen_tables.add(best_table)
        elif cand not in resolved_terms:
            unresolved.append(cand)

    return TableResolution(
        matched=matched,
        fuzzy=fuzzy,
        unresolved=unresolved,
    )


def build_resolution_hints(resolution: TableResolution) -> str:
    """Build a short text block with hints for the orchestrator prompt."""
    if not resolution.fuzzy and not resolution.unresolved:
        return ""

    parts: list[str] = []
    for term, closest, score in resolution.fuzzy:
        parts.append(
            f"NOTE: '{term}' might refer to table '{closest}' "
            f"(confidence {score:.0%}). Verify with the user if unclear."
        )
    if resolution.unresolved:
        terms = ", ".join(f"'{t}'" for t in resolution.unresolved[:5])
        parts.append(
            f"WARNING: The user's question references {terms} which "
            "does not match any known table. Use ask_user to clarify "
            "which table or data source they mean before proceeding."
        )
    return "\n".join(parts)
