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
