"""Coercion at the boundary where a model's tool call becomes application data.

A tool schema declares a parameter ``type="string"``. A model is free to ignore that,
and one does: after ``DEFAULT_LLM_MODEL`` moved to ``deepseek/deepseek-v4-flash-0731``
on 2026-09-10, JSON **objects** started arriving where JSON **strings** had before.
Every one of those values is destined for a ``Text`` column, so the failure surfaced as
``asyncpg.exceptions.DataError: invalid input for query argument $6: {} (expected str)``
and four consecutive nightly ``code_db_sync`` runs stored nothing while reporting they
had run.

The rule this module exists to state once: **a tool-call argument is untrusted input,
and its declared type is a request, not a guarantee.** Parse it at the boundary or the
database will, and the database's refusal arrives hours later in a background job.

Two sites had an ad-hoc ``isinstance(x, dict)`` guard on one field each and none on
their neighbours, which is how the same round of a model's output both broke a writer
and was survived by the writer beside it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def as_text(value: Any, default: str = "") -> str:
    """Return *value* as a ``str``, whatever the model actually sent.

    A dict or list is serialised as JSON; a scalar is stringified; ``None`` and anything
    that will not serialise become *default*. Degrading to the default is deliberate: a
    lost note is a gap the prompt works around, while a dict handed to the driver is a
    run that stores nothing at all.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return default
    if isinstance(value, dict | list):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            logger.warning(
                "tool args: unserialisable %s argument, using the default",
                type(value).__name__,
            )
            return default
    if isinstance(value, bool | int | float):
        return str(value)
    logger.warning(
        "tool args: unexpected %s argument where a string was declared, using the default",
        type(value).__name__,
    )
    return default


def as_int(value: Any, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    """Coerce a tool-call argument the schema declared ``integer`` into one.

    Same premise as :func:`as_text`: the declared type is a request. ``int({})``
    raises inside whatever ``try`` happens to surround the call, and in
    ``db_index_validator`` that discards the LLM analysis of the table **and of
    every table after it in the batch** — a bad score on one row losing the work
    done on twelve.

    A string of digits is accepted (models return ``"4"`` routinely); a float is
    rounded rather than truncated, because ``"4.5"`` from a model means four-ish,
    not four. Anything else degrades to *default*, clamped to ``[lo, hi]``.
    """
    out: int
    if isinstance(value, bool):
        out = int(value)
    elif isinstance(value, int):
        out = value
    elif isinstance(value, float):
        out = round(value)
    elif isinstance(value, str):
        try:
            out = round(float(value.strip()))
        except (TypeError, ValueError):
            logger.warning("tool args: %r is not a number, using the default", value[:40])
            out = default
    else:
        logger.warning(
            "tool args: unexpected %s where an integer was declared, using the default",
            type(value).__name__,
        )
        out = default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def as_bool(value: Any, default: bool) -> bool:
    """Coerce a tool-call argument the schema declared ``boolean`` into one.

    ``bool({})`` is ``False`` and ``bool("false")`` is ``True`` — both silent, and
    the second is the one a model produces. A bare string is read for its meaning;
    anything unrecognised takes *default* rather than a coin flip.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "yes", "1", "y", "on"}:
            return True
        if token in {"false", "no", "0", "n", "off"}:
            return False
    logger.warning("tool args: %r is not a boolean, using the default", str(value)[:40])
    return default


def as_float(value: Any, default: float) -> float:
    """Coerce a tool-call argument the schema declared ``number`` into one.

    ``float({})`` raises, and in `learning_analyzer` that loop sits outside the
    only ``try`` in the function, so the exception escaped to a caller logging at
    DEBUG: one malformed element lost every lesson the model had extracted, with
    no line in the log to say so.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            logger.warning("tool args: %r is not a number, using the default", value[:40])
            return default
    logger.warning(
        "tool args: unexpected %s where a number was declared, using the default",
        type(value).__name__,
    )
    return default


#: ``finish_reason`` values every supported provider uses to say "I ran out of room".
#: OpenAI and OpenRouter emit ``length``; Anthropic emits ``max_tokens``.
TRUNCATION_FINISH_REASONS = frozenset({"length", "max_tokens"})


def tool_call_truncated(response: Any) -> bool:
    """True when the model was cut off mid-tool-call and the arguments are unusable.

    A provider says this plainly — ``finish_reason`` is ``length`` (OpenAI, OpenRouter)
    or ``max_tokens`` (Anthropic) — and until 2026-09-15 **nothing in the product read
    it**: all three adapters set the field on ``LLMResponse`` and no production code
    path ever looked at it.

    What that cost, measured on production the day it was found. Arguments arrive as a
    JSON *string*, so a generation stopped at the cap leaves the object unclosed;
    ``json.loads`` raises, and the OpenRouter adapter substituted ``args = {}`` and
    appended the tool call anyway. The caller could not tell that from a model which
    had genuinely answered with nothing to say, so ``_analysis_from_args({})`` wrote a
    complete row of defaults — ``sync_status="unknown"``, ``confidence_score=3``, every
    prose field empty — and recorded it as a real analysis with ``is_fallback=False``.

    That is what blinded the guard built for exactly this degradation.
    ``code_db_sync_pipeline`` refuses to persist when the non-fallback ratio falls below
    ``sync_min_success_ratio_to_persist``, so the previous night's good rows survive an
    LLM outage — and a truncated call is not a fallback, so the ratio read 100% while
    every row was empty. Production on 2026-09-15: **126 of 263 map rows at
    ``unknown``, 129 with no column notes, 121 at the default confidence**, written over
    a map that had held 138 ``matched`` rows before the model changed.

    The cap was the trigger, not the cause. ``SYNC_ANALYSIS_TOOL`` declares ten
    parameters, three of them long prose, and the per-table call allowed 2048 completion
    tokens: measured against fourteen real production tables, **every one of the
    fourteen stopped at exactly 2048**. ``sync_status`` is emitted in schema order and
    sat ninth of ten, so the decision was the first thing the cap removed — which is why
    the failure looked like a model that would not decide rather than one never asked.

    So this is checked at every site that hands a tool to a model with a cap, and a
    truncated call is refused rather than parsed. Raising the cap alone would only move
    the boundary; a document this size will find it again.
    """
    reason = getattr(response, "finish_reason", "") or ""
    if str(reason).lower() in TRUNCATION_FINISH_REASONS:
        return True
    # Belt two: a provider that reports no reason, or reports one we do not know,
    # still cannot produce a tool call whose arguments failed to parse. The adapters
    # substitute an empty mapping there, and an empty mapping is never a real answer
    # to a schema whose first parameter is required.
    calls = getattr(response, "tool_calls", None) or []
    return bool(calls) and not any(getattr(c, "arguments", None) for c in calls)
