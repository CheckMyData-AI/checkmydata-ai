"""One answer to "is this value a number?", because the repository had 22.

A sweep on 2026-09-05 found twenty-two numeric guards across `app/`, in five
mutually inconsistent variants, of which exactly one was right:

    (int, float)                                  13 sites  Decimal out, bool in
    (int, float, Decimal)                          2 sites  bool in
    (int, float) + not bool                        3 sites  Decimal out
    int | float | Decimal                          1 site   bool in
    (int, float, Decimal) + not bool               1 site   correct

Two failure modes follow from the variants, and they point opposite ways.

**Rejecting ``Decimal`` makes money invisible.** `asyncpg` returns a Postgres
``NUMERIC`` as ``decimal.Decimal``, and `connectors/mongodb.py:134` converts
``Decimal128`` to the same type on purpose, "like asyncpg's numeric results". So
the guard that omits it does not merely lose precision — it decides that a
revenue column contains no numbers at all, on exactly the columns a loss
detector exists to watch.

**Accepting ``bool`` turns a flag into a measurement.** ``bool`` subclasses
``int``, so ``is_active`` averages as 0.6 and a detector reports a trend in it.

This module is a stdlib-only leaf so that `app/core`, `app/agents` and `app/viz`
can all import it without inverting a dependency — the same reason
`app/core/failure_kind.py` and `app/core/identity.py` exist.

**What is deliberately NOT decided here:** infinities pass. Every call site
already accepted them and no evidence says they cause harm; silently changing
that alongside two fixes with evidence would make the change unreviewable. It is
recorded on the board rather than folded in.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

__all__ = ["is_measurement", "to_number"]

_NUMERIC_TYPES = (int, float, Decimal)


def is_measurement(value: Any) -> bool:
    """True when *value* is a number something can be measured from.

    Excludes ``bool`` (a flag is not a measurement) and NaN in both its float
    and its ``Decimal`` spelling. Accepts ``Decimal``, which is how every
    connector in this codebase delivers a fixed-point column.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, _NUMERIC_TYPES):
        return False
    if isinstance(value, Decimal):
        # `Decimal('sNaN') == Decimal('sNaN')` RAISES InvalidOperation rather
        # than comparing unequal, so the `val == val` idiom every call site used
        # would have propagated an exception out of a predicate. Found by the
        # test, not by reading.
        return not value.is_nan()
    # Only int and float remain here, and `math.isnan` accepts both. The first
    # draft used the `value == value` idiom every call site writes, which needs a
    # PLR0124 suppression beside it — and the suppression-debt ratchet failed the
    # build for exactly that. Correctly: the suppression was avoidable, and
    # raising a ceiling to keep an avoidable one is how a ratchet stops meaning
    # anything. (Spelling the directive out in this comment re-armed it, because
    # the linter reads a mention as a directive — hence the prose.)
    return not math.isnan(value)


def to_number(value: Any) -> float | None:
    """Coerce *value* to ``float``, or ``None`` when it is not a measurement.

    ``float`` rather than ``Decimal`` on purpose: the callers are statistical —
    means, standard deviations, ratios — and they render through ``:,.0f``. The
    defect being fixed is that a ``Decimal`` was not seen at all, not that its
    precision was lost afterwards. A caller that must preserve exactness should
    keep the ``Decimal`` and not come through here.
    """
    if not is_measurement(value):
        return None
    # No try/except, and that is deliberate. The first draft carried one, with a
    # comment claiming a Decimal outside float range raises OverflowError.
    # Measured: `float(Decimal("1e400"))` returns `inf`, and the only raising case
    # — `Decimal("sNaN")`, a ValueError — is already excluded by is_measurement.
    # So the handler could only ever have swallowed a defect, which is the exact
    # failure mode `tests/unit/test_fire_and_forget_calls_bind.py` exists to stop.
    return float(value)
