"""Enforce code-DB / index required filters before executing SQL.

SYNC-L1 (prod incident #1): the guard is DATA-DRIVEN and SATISFIABLE.

**The predicate is prose, and the parser must expect that (2026-08-31).** These
predicates are written by an LLM, and the tool description that asks for them gives
this example verbatim::

    {"status": "= 1 (processed only)", "deleted_at": "IS NULL (exclude soft-deleted)"}

The old parser took everything after ``=`` — commentary included — and escaped it into
the pattern, yielding ``was_handled\\s*=\\s*1\\ \\(processed\\ only\\)\\b``, which no SQL
can satisfy. Anything it could not parse fell back to a bare ``\\bcol\\b`` presence check,
which a mention in the SELECT list satisfies. Measured against production: **159
predicates configured, 1 satisfiable** — 59 unsatisfiable across 57 tables, 98 vacuous.

Three rules now hold, and the third is the one that was missing:

1. Parse from the LEFT — operator, then operand. A tail is accepted only when it is
   empty or wholly parenthesised commentary. ``= 'pending' or 'completed'`` is a
   disjunction this cannot express, so it is not enforced rather than half-enforced.
2. A **bound** is satisfied by a tighter bound. ``created_at >= '2023-01-01'`` means
   "exclude pre-2023"; a six-month window satisfies it. Demanding the literal date
   would false-block nearly every question, since most ask about a recent period.
3. **An unenforceable requirement is not claimed as checked.** ``"must filter by
   specific type"`` compiles to nothing; it is skipped and counted, never converted into
   a presence check that reports a pass it did not perform. It still reaches the model
   as prompt context, which is where an instruction of that shape belongs.

Satisfiable / degrade-not-die: on the *final* attempt an unsatisfied filter DEGRADES to
a user-facing warning and the answer proceeds. Earlier attempts hard-fail so the repair
loop can add the missing predicate — which it now can, because the predicate is real.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.query_validation import QueryError, QueryErrorType, ValidationResult
from app.core.sql_parser import extract_table_aliases, extract_tables
from app.core.sql_text import masked_spans, starts_inside_masked

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Predicate compilation
# ---------------------------------------------------------------------------

# A column reference as SQL actually spells it: optionally alias-qualified
# (``o.was_handled``) and optionally quoted (``\`was_handled\``, ``"was_handled"``).
# The lookbehind rejects a longer identifier ending in the same word, so a required
# ``was_handled`` is not satisfied by ``prev_was_handled``.
_Q_OPEN = r"[`\"\[]?"
_Q_CLOSE = r"[`\"\]]?"

# Operand as it appears in a stored predicate: quoted string, or a bare token wide
# enough for numbers and unquoted dates (``>= 2023-01-01`` occurs in production).
_OPERAND = r"'[^']*'|\"[^\"]*\"|[\w.:+-]+"

# A range requirement ("created_at >= '2023-01-01'", "status BETWEEN 1 AND 5") states
# which rows are VALID, so any narrowing of that column satisfies it: `= 2` is inside
# `BETWEEN 1 AND 5`, and a six-month window is inside "not before 2023". What it cannot
# tolerate is the column going unconstrained. `IS NULL` is deliberately absent — it
# filters, but it does not bound a range.
_ANY_COMPARISON = r"\s*(?:!=|<>|>=|<=|=|>|<|(?:NOT\s+)?IN\b|BETWEEN\b)"


def _col_atom(col: str, qualifiers: frozenset[str] | None = None) -> str:
    """The column, optionally required to carry a table qualifier.

    Without ``qualifiers`` a bare ``deleted_at`` matches — correct when the query
    names one table, where nothing else it could belong to. With them, only
    ``o.deleted_at`` / ``orders.deleted_at`` matches, which is what stops a
    predicate on one side of a join from satisfying the other side's requirement.
    """
    bare = rf"{_Q_OPEN}{re.escape(col)}{_Q_CLOSE}"
    if not qualifiers:
        return rf"(?<!\w){bare}"
    alts = "|".join(re.escape(q) for q in sorted(qualifiers))
    return rf"(?<!\w){_Q_OPEN}(?:{alts}){_Q_CLOSE}\s*\.\s*{bare}"


def _tail_is_commentary(tail: str) -> bool:
    """A predicate may carry a trailing note; it may not carry more predicate.

    Empty or wholly parenthesised is commentary. Anything else — ``or 'completed'``,
    ``AND status != 'x'`` — is a condition this parser cannot express, and pretending
    otherwise is how a half-read predicate becomes a false block.
    """
    t = tail.strip()
    return not t or bool(re.fullmatch(r"\(.*\)", t, re.DOTALL))


def _value_alternatives(raw: str) -> str:
    """Match one stored operand against the forms SQL writes it in.

    Quote style varies by dialect and by whoever wrote the query; ``1`` and ``TRUE``
    are the same value to MySQL and the model uses both.
    """
    v = raw.strip()
    quoted = re.fullmatch(r"(['\"])(.*)\1", v, re.DOTALL)
    if quoted:
        inner = re.escape(quoted.group(2))
        alts = [f"'{inner}'", f'"{inner}"']
    else:
        esc = re.escape(v)
        alts = [esc, f"'{esc}'", f'"{esc}"']
        if v == "1":
            alts.append("TRUE")
        elif v == "0":
            alts.append("FALSE")
    return "(?:" + "|".join(alts) + ")"


def parse_predicate(
    col: str, predicate: str, qualifiers: frozenset[str] | None = None
) -> str | None:
    """Compile a stored predicate into a regex fragment, or ``None`` if it is not a
    predicate at all.

    ``None`` means *unenforceable*, which is different from *unsatisfied*: the caller
    must skip it rather than fail it, and must not report it as checked.
    """
    p = (predicate or "").strip()
    if not p:
        return None

    # Some writers repeat the column ("deleted_at IS NULL"); drop it and read the rest.
    lead = re.match(rf"^{_Q_OPEN}{re.escape(col)}{_Q_CLOSE}\s+", p, re.IGNORECASE)
    if lead:
        p = p[lead.end() :].strip()

    c = _col_atom(col, qualifiers)

    m = re.match(r"^IS\s+NOT\s+NULL(?P<tail>.*)$", p, re.IGNORECASE | re.DOTALL)
    if m and _tail_is_commentary(m.group("tail")):
        return rf"{c}\s+IS\s+NOT\s+NULL(?!\w)"

    m = re.match(r"^(?:IS\s+NULL|=\s*NULL)(?P<tail>.*)$", p, re.IGNORECASE | re.DOTALL)
    if m and _tail_is_commentary(m.group("tail")):
        return rf"{c}\s+IS\s+NULL(?!\w)"

    m = re.match(r"^(?:NOT\s+)?IN\s*\([^)]*\)(?P<tail>.*)$", p, re.IGNORECASE | re.DOTALL)
    if m and _tail_is_commentary(m.group("tail")):
        return rf"{c}\s+(?:NOT\s+)?IN\s*\("

    if re.match(r"^BETWEEN\b", p, re.IGNORECASE):
        return rf"{c}{_ANY_COMPARISON}"

    m = re.match(
        rf"^(?P<op>>=|<=|<>|!=|==|=|>|<)\s*(?P<val>{_OPERAND})(?P<tail>.*)$",
        p,
        re.DOTALL,
    )
    if m and _tail_is_commentary(m.group("tail")):
        op = m.group("op")
        if op in (">", ">=", "<", "<="):
            # This is what makes "revenue for the last 6 months" legal under a
            # ">= 2023-01-01" rule, while `SELECT created_at FROM t` stays illegal.
            return rf"{c}{_ANY_COMPARISON}"
        value = _value_alternatives(m.group("val"))
        operator = r"=" if op in ("=", "==") else r"(?:!=|<>)"
        return rf"{c}\s*{operator}\s*{value}(?!\w)"

    return None


def compile_filter_check(
    col: str, predicate: str, qualifiers: frozenset[str] | None = None
) -> re.Pattern[str] | None:
    """Compile a required predicate into a pattern that must appear in the query.

    Returns ``None`` when the stored text is not a predicate (an instruction such as
    "must filter by specific type"). Callers must skip those: the previous behaviour —
    a bare column-presence check — reported a pass it had not performed.
    """
    fragment = parse_predicate(col, predicate, qualifiers)
    return re.compile(fragment, re.IGNORECASE) if fragment else None


# ---------------------------------------------------------------------------
# Normalisation: accept both legacy set-form and new dict-form
# ---------------------------------------------------------------------------

# Built-in fallback predicates for the two legacy known columns so that
# callers still using the old ``{table: set[str]}`` form continue to work.
_LEGACY_PREDICATES: dict[str, str] = {
    "was_handled": "= 1",
    "deleted_at": "IS NULL",
}


def _normalize_required(
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Accept either ``{table: {col}}`` (legacy) or ``{table: {col: predicate}}``
    (data-driven).

    Legacy set form falls back to the built-in predicate for the 2 known columns
    and an empty predicate otherwise, which the guard treats as unenforceable.
    """
    out: dict[str, dict[str, str]] = {}
    for table, cols in required_by_table.items():
        if isinstance(cols, dict):
            out[table.lower()] = dict(cols)
        else:
            out[table.lower()] = {c: _LEGACY_PREDICATES.get(c, "") for c in cols}
    return out


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def parse_required_columns_from_hint(hint: str) -> set[str]:
    """Extract required filter column names mentioned in db_index query_hints."""
    if not hint:
        return set()
    lower = hint.lower()
    required: set[str] = set()
    if "was_handled" in lower:
        required.add("was_handled")
    if "deleted_at" in lower and "null" in lower:
        required.add("deleted_at")
    return required


def merge_required_filters(
    sync_filters: dict[str, dict[str, str]],
    index_hints: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Merge code_db_sync required_filters_json with db_index query_hints per table.

    Returns ``dict[str, dict[str, str]]`` — column → predicate string — so that
    data-driven predicates from ``required_filters_json`` (e.g. ``is_active = 1``)
    are preserved end-to-end and not reduced to bare column names.

    Columns sourced only from index hints receive their legacy predicate via
    ``_LEGACY_PREDICATES`` (or an empty string for unknown columns, which the guard
    treats as unenforceable rather than inventing a check for it).
    """
    merged: dict[str, dict[str, str]] = {}
    for table, filters in sync_filters.items():
        key = table.lower()
        col_preds: dict[str, str] = dict(filters)  # preserve predicates from sync
        hint_cols = parse_required_columns_from_hint(index_hints.get(table, ""))
        for c in hint_cols:
            col_preds.setdefault(c, _LEGACY_PREDICATES.get(c, ""))
        if col_preds:
            merged[key] = col_preds
    for table, hint in index_hints.items():
        key = table.lower()
        hint_cols = parse_required_columns_from_hint(hint)
        if hint_cols:
            existing = merged.setdefault(key, {})
            for c in hint_cols:
                existing.setdefault(c, _LEGACY_PREDICATES.get(c, ""))
    return merged


def _inc(metric: str, **labels: str) -> None:
    """Metrics must never break the guard."""
    try:
        from app.core.metrics import get_metrics_collector

        # `amount` is positional: forwarding **labels alone lets a label named
        # `amount` bind to it, which mypy catches and a runtime never would.
        get_metrics_collector().inc(metric, 1, **labels)
    except Exception:  # pragma: no cover
        pass


def check_required_filters(
    query: str,
    db_type: str,
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
    *,
    attempt: int = 1,
    max_attempts: int = 3,
) -> ValidationResult:
    """Data-driven, satisfiable guard (SYNC-L1, C-F).

    Fails when a referenced table is missing a configured required filter that could
    be compiled. A requirement that is not a predicate is skipped and counted, never
    reported as satisfied. On the *final* attempt an unsatisfied required filter
    DEGRADES to a valid result carrying a user-facing warning (never a hard-fail), and
    increments ``filter_guard_degrade_total``.
    """
    if db_type.lower() in {"mongodb", "mongo"} or not required_by_table:
        return ValidationResult(is_valid=True)

    normalized = _normalize_required(required_by_table)
    tables = {t.lower() for t in extract_tables(query)}
    if not tables:
        return ValidationResult(is_valid=True)

    # Positional masking, not blanking. Until 2026-09-05 this searched the raw
    # text, so a required predicate was satisfied by the same characters sitting
    # in a comment or a string literal. The first fix blanked literals outright
    # and broke four existing tests at once: a required predicate usually
    # CONTAINS one — `status = 'active'` — so erasing them made every such
    # requirement unsatisfiable, which is what
    # `test_every_shape_is_satisfiable_by_some_query` exists to catch. The
    # distinction is where the match STARTS: inside a literal it is text, outside
    # it the literal may be its operand.
    masked = masked_spans(query, db_type)

    # Bind each predicate to its table when there is more than one to confuse it
    # with. A two-table join requiring `deleted_at IS NULL` on both passed when
    # only one side was filtered, because nothing tied the occurrence to a table.
    # With a single table a bare column is unambiguous, and demanding
    # `orders.deleted_at` there would false-block most correct SQL — which costs
    # an unsatisfiable repair loop, measured at ~23 s per query.
    alias_map = extract_table_aliases(query, db_type) if len(tables) > 1 else {}

    missing: list[str] = []
    for table in tables:
        preds = normalized.get(table)
        if not preds:
            continue
        for col, predicate in sorted(preds.items()):
            qualifiers = (
                frozenset(a for a, t in alias_map.items() if t == table) or None
                if alias_map
                else None
            )
            pattern = compile_filter_check(col, predicate or "", qualifiers)
            if pattern is None:
                # Not a predicate — an instruction, a disjunction, or empty. It reaches
                # the model as prompt context; it is not a check, and is not counted as
                # one in either direction.
                _inc("required_filter_unenforceable_total", db_type=db_type.lower())
                continue
            if not any(
                not starts_inside_masked(m.start(), masked) for m in pattern.finditer(query)
            ):
                missing.append(f"{table}.{col}")

    if not missing:
        return ValidationResult(is_valid=True)

    cols_str = ", ".join(missing)

    # Satisfiability: after the final attempt, degrade to a warning instead of a
    # hard fail so we never block a legitimate query to death (prod incident #1).
    if attempt >= max_attempts:
        _inc("filter_guard_degrade_total", db_type=db_type.lower())
        return ValidationResult(
            is_valid=True,
            warning=(
                f"Could not apply required filter(s) after {max_attempts} attempts: {cols_str}. "
                "The answer is returned WITHOUT them — treat totals as potentially including "
                "invalid/soft-deleted rows and verify against the business definition."
            ),
        )

    return ValidationResult(
        is_valid=False,
        error=QueryError(
            error_type=QueryErrorType.UNKNOWN,
            message=(
                f"Query is missing required filter(s): {cols_str}. Add them to WHERE and retry."
            ),
            raw_error=f"required_filter_guard: missing {cols_str}",
            is_retryable=True,
            schema_hint=(
                "Required filters (from code-DB sync / schema index). Add every "
                "missing predicate to the WHERE clause before aggregating."
            ),
        ),
    )
