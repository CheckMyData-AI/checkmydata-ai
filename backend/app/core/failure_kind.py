"""The one definition of "why did this fail" (Ш0 · REQ-4).

Four tables carry a ``failure_kind String(20)`` column — ``request_traces``,
``query_failures``, ``error_logs``, ``indexing_runs`` — and until this module
nothing in the codebase said what may go in it. Two vocabularies were in use and
they disagreed: :mod:`app.api.routes.chat` wrote ``"transient"``/``"fatal"``,
while :class:`~app.agents.stage_context.StageResult` classified into four values
and *acted* on them — ``retryable`` is ``error_category == "transient"``, and a
non-retryable category short-circuits the retry ladder instead of spending the
plan's budget.

The four here are that second set, unchanged. It is the richer one and it is
already load-bearing, so adopting it costs nothing and inventing a third would
have been the actual mistake.

Production, measured 2026-09-03: the column was NULL in **all 56** failed traces
and **all 50** query failures. Filling it from two vocabularies would have
replaced *no answer* with *an answer nobody can group by* — worse, because a
reader believes a populated column.

Nothing but the standard library may be imported here, and a test enforces it.
The reason is the one :mod:`app.analytics.source_types` records: this is imported
by the agents, the routes, the services and the models, and a vocabulary module
that drags in SQLAlchemy cannot be reached from the light side of a split — so
somebody writes the second copy instead, which is how the drift started.
"""

from __future__ import annotations

from typing import Literal

#: Why a request, query, indexing run or logged error ended badly.
#:
#: ``transient``     — the same attempt could succeed: an overloaded provider, a
#:                     dropped connection, a lock timeout. **The only retryable one.**
#: ``configuration`` — the system is wired wrong or a resource is absent: a bad
#:                     credential, a connection that does not exist, a tool with
#:                     no source behind it. Retrying cannot make it appear.
#: ``data_missing``  — the machinery worked and the data was not there. Recoverable
#:                     by taking a different route (a replan), not by repetition.
#: ``fatal``         — a defect or an unclassifiable failure. Stops the run.
FailureKind = Literal["transient", "configuration", "data_missing", "fatal"]

#: The vocabulary, as a tuple so a caller cannot extend it in place. Order is
#: stable because it reaches ``IN`` lists and log lines.
FAILURE_KINDS: tuple[FailureKind, ...] = (
    "transient",
    "configuration",
    "data_missing",
    "fatal",
)

#: Derived, never typed twice — the second copy is what drifts.
NON_RETRYABLE_KINDS: tuple[FailureKind, ...] = tuple(k for k in FAILURE_KINDS if k != "transient")


# Named constants, so a call site reads as a decision rather than as a string.
# A literal at the call site is what let the two vocabularies drift in the first
# place, and a test refuses `failure_kind="..."` in the routes because of it.
TRANSIENT: FailureKind = "transient"
CONFIGURATION: FailureKind = "configuration"
DATA_MISSING: FailureKind = "data_missing"
FATAL: FailureKind = "fatal"


def is_retryable(kind: str | None) -> bool:
    """Is another identical attempt worth making?

    Fails closed: an unrecognised value, ``None`` and ``""`` are all
    **not** retryable. A misconfiguration must not buy a second attempt out of
    the budget that exists to stop a runaway.
    """
    return kind == "transient"


def normalise_failure_kind(kind: str | None) -> FailureKind | None:
    """Coerce a caller's value into the vocabulary, or ``None``.

    ``None``/``""`` stay ``None``: a successful run has no failure kind, and
    calling that ``fatal`` would invent a failure.

    An unrecognised non-empty string becomes ``fatal`` rather than being stored
    raw. Two reasons, and the second is the one that matters: the column is only
    groupable if every value is in the vocabulary, and dropping the signal
    entirely would put the row back in the all-NULL state this module exists to
    leave.
    """
    if kind is None:
        return None
    cleaned = kind.strip().lower()
    if not cleaned:
        return None
    if cleaned in FAILURE_KINDS:
        # mypy narrows this correctly: FAILURE_KINDS is typed as a tuple of
        # FailureKind, so membership in it proves the Literal. No cast needed,
        # and one was written here first — the type checker was right.
        return cleaned
    return "fatal"
