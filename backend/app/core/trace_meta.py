"""What a finished request must say about itself (Ш0 · REQ-1).

``finalize_trace`` already accepted ``route``, ``complexity``,
``estimated_queries`` and ``failure_kind`` as keyword arguments with defaults.
Production, measured 2026-09-03: **zero of its twelve call sites passed any of
them**, so `route` and `complexity` read ``"unknown"`` in 222 traces out of 222 —
while ``CLAUDE.md`` claimed *"routing metrics always populated (ORCH-A03)"*. That
claim was true of ``MetricsCollector``, which holds them in memory, and false of
the row anybody can query afterwards.

A default is what made it silent. The fix is the shape #267 arrived at for the
same failure: ``ConnectionService.get_in_project`` exists because the project
check *"is written out verbatim in six sibling route modules and absent from the
three that matter most"* — a call that cannot be made without the value cannot
forget it at a thirteenth entry point.

So this record is **required** by ``finalize_trace``, and every caller states
which kind of run it is finishing:

* :meth:`TraceMeta.from_response` — an agent answered; the routing is real.
* :meth:`TraceMeta.aborted` — the agent timed out or crashed, so there is no
  response to read routing from, and the failure kind is the point.
* :meth:`TraceMeta.utility` — a non-agent trace (title generation, an MCP tool).
  Routing is genuinely absent here, and saying so explicitly is different from
  defaulting to it.

Standard library only, and a test enforces it: this is imported by the
orchestrator, the chat routes, the MCP server and the trace service, and a record
that drags in SQLAlchemy cannot be reached from all four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.failure_kind import FailureKind, normalise_failure_kind

#: ``price_source`` values. A cost figure without its provenance cannot be
#: audited later: the same number means different things depending on whether a
#: live price produced it or a stale snapshot did.
PRICE_SOURCES: tuple[str, ...] = ("none", "process_cache", "shared_cache", "static")

#: What ``route``/``complexity`` say when nothing supplied them. Kept as a named
#: constant rather than a bare string so the 222-row production symptom is
#: greppable from the code that produces it.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class TraceMeta:
    """The routing, failure and cost facts of one finished request.

    Frozen: it is a statement about a run that has already happened, and a
    caller mutating it after the fact is how a trace stops matching the run.
    """

    route: str = UNKNOWN
    complexity: str = UNKNOWN
    estimated_queries: int = 0
    failure_kind: FailureKind | None = None
    cost_usd: float | None = None
    #: Where ``cost_usd`` came from. ``"none"`` when no price was available —
    #: which is honest, and distinct from a cost of zero.
    price_source: str = "none"

    def __post_init__(self) -> None:
        if self.price_source not in PRICE_SOURCES:
            raise ValueError(
                f"unknown price_source {self.price_source!r}; expected one of {PRICE_SOURCES}"
            )
        if self.cost_usd is None and self.price_source != "none":
            raise ValueError(
                f"price_source={self.price_source!r} claims a price produced a cost, "
                "but cost_usd is None"
            )

    # ------------------------------------------------------------------
    # Constructors — one per kind of run, so a caller cannot be vague
    # ------------------------------------------------------------------

    @classmethod
    def from_response(cls, response: Any, *, failure_kind: str | None = None) -> TraceMeta:
        """Read the routing an agent actually took off its response.

        ``getattr`` rather than a typed parameter: ``AgentResponse`` lives in
        ``app.agents.orchestrator``, importing it here would invert the
        dependency, and this module has to stay standard-library-only. A
        response missing a field degrades that field to ``UNKNOWN`` instead of
        raising — a trace is worth writing even when one of its facts is absent.
        """
        return cls(
            route=str(getattr(response, "route", "") or UNKNOWN),
            complexity=str(getattr(response, "complexity", "") or UNKNOWN),
            estimated_queries=int(getattr(response, "estimated_queries", 0) or 0),
            failure_kind=normalise_failure_kind(
                failure_kind
                if failure_kind is not None
                else getattr(response, "failure_kind", None)
            ),
            cost_usd=getattr(response, "cost_usd", None),
            price_source=str(getattr(response, "price_source", "") or "none"),
        )

    @classmethod
    def aborted(cls, failure_kind: str) -> TraceMeta:
        """The run never produced a response — a timeout or an exception.

        Routing stays ``UNKNOWN`` and that is the truth: the router may not have
        run at all. ``failure_kind`` is required, because a trace written from
        this constructor exists precisely to record why.
        """
        kind = normalise_failure_kind(failure_kind)
        if kind is None:
            raise ValueError("aborted() requires a failure kind; use utility() for a clean run")
        return cls(failure_kind=kind)

    @classmethod
    def utility(cls, route: str = "utility", *, failure_kind: str | None = None) -> TraceMeta:
        """A trace with no agent behind it — title generation, an MCP tool call.

        Routing is genuinely absent rather than lost, and ``route="utility"``
        says so. A query over the traces can then separate *"nobody wired the
        router"* from *"this request had no router to wire"*, which the single
        ``"unknown"`` value could not.
        """
        return cls(route=route, failure_kind=normalise_failure_kind(failure_kind))

    # ------------------------------------------------------------------

    def with_cost(self, cost_usd: float | None, price_source: str) -> TraceMeta:
        """Return a copy carrying a cost. Frozen records are replaced, not edited."""
        from dataclasses import replace

        return replace(self, cost_usd=cost_usd, price_source=price_source)
