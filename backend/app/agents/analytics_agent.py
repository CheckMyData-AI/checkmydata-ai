"""AnalyticsAgent — answers analytics questions from the **local** fact tables.

The vendor is never contacted here. Collection already happened on a schedule
(:mod:`app.services.analytics_collect_service`), landing rows in the ``ga4_*``
tables and a verdict per period in the journal
(:mod:`app.analytics.journal`). This agent reads both, and the second one is the
reason it exists in its own module rather than being folded into ``SQLAgent``:

    **An absent row is not a zero.**

"July 11 had no sessions" and "July 11 was never collected" produce the same
empty result set, and only the journal can tell them apart. A SQL agent pointed
at these tables would answer 0 to both — a fabricated measurement, which vision
§7 forbids outright. So every read here is paired with a coverage lookup, and
the honest caveat is appended by *this code* after the model answers rather than
requested of the model in a prompt: an honesty guarantee that depends on the
model complying with an instruction is not a guarantee.

Two more consequences of reading local tables shape the design:

* **No free-form SQL, ever.** The three tools are parameterised readers. A report
  name resolves through :data:`REPORT_BINDINGS` to a SQLAlchemy model, a
  ``group_by`` resolves to a real ``Column`` object, dates parse to ``date`` and
  travel as bound parameters. No caller-supplied string is ever concatenated
  into a statement — see :meth:`ReportBinding.resolve_group_by`, which raises
  rather than interpolate.
* **The catalogue is derived, not restated.** :data:`REPORT_BINDINGS` is built
  from :data:`app.analytics.ga4.reports.GA4_REPORTS`, so the allow-list cannot
  drift from what the collector actually writes; a report whose columns stop
  matching its model fails at import instead of at query time.

The loop shape follows :class:`~app.agents.mcp_source_agent.MCPSourceAgent`:
bounded iterations, truncated tool results, and ``no_result`` — never a composed
answer — when the budget runs out.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.data_gate import DataGate
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.analytics_prompt import build_analytics_system_prompt
from app.analytics.ga4.reports import GA4_REPORTS, GA4ReportSpec
from app.analytics.journal import DONE_STATUSES
from app.config import settings
from app.connectors.base import QueryResult
from app.core.history_trimmer import trim_loop_messages
from app.llm.base import LLMResponse, Message, Tool, ToolCall, ToolParameter
from app.llm.retry import llm_call_with_retry
from app.llm.router import LLMRouter
from app.models.analytics_ga4 import (
    GA4EventDaily,
    GA4GeoDaily,
    GA4OverviewDaily,
    GA4PlatformDaily,
    GA4TrendDaily,
)
from app.models.analytics_import import AnalyticsImport

logger = logging.getLogger(__name__)

#: Column every fact table carries besides its report's own dimensions.
PROPERTY_COLUMN = "property_id"

#: Hard ceiling on rows returned by one ``query_report`` call, and the default
#: when the model does not ask for one. The cap is not cosmetic: the rows go
#: into the LLM context, so an unbounded read is an unbounded prompt.
MAX_ROW_LIMIT = 1000
DEFAULT_ROW_LIMIT = 200

#: Longest window (in periods) a single call may span. Beyond this the coverage
#: enumeration stops being a useful answer and starts being a denial of service.
MAX_WINDOW_PERIODS = 1100

#: How many missing/failed periods are named before the caveat summarises.
MAX_NAMED_PERIODS = 8

#: Caps on what one tool result contributes to the context / to the trace.
TOOL_RESULT_CHARS = 4000
TOOL_PREVIEW_CHARS = 2000

#: Maps a GA4 field's storage kind onto a :class:`~app.agents.data_gate.DataGate`
#: semantic kind. ``decimal`` is revenue, and revenue can legitimately be
#: negative (refunds), so it is an ``amount`` — never a ``count``, whose hard
#: check rejects negatives.
_DATA_GATE_KINDS: Mapping[str, str] = {
    "date": "date",
    "int": "count",
    "decimal": "amount",
    "str": "other",
}

_GA4_MODELS_BY_REPORT: Mapping[str, type[Any]] = {
    "overview": GA4OverviewDaily,
    "geo": GA4GeoDaily,
    "platform": GA4PlatformDaily,
    "trend": GA4TrendDaily,
    "events": GA4EventDaily,
}


# ---------------------------------------------------------------------------
# The allow-list
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportBinding:
    """One report, bound to the table it is read from.

    This *is* the security boundary for :meth:`AnalyticsAgent.run`: a report
    name and a ``group_by`` are only ever accepted by matching them against the
    tuples here and returning the corresponding mapped attribute. Nothing
    downstream sees the caller's string.
    """

    name: str
    description: str
    grain: str
    model: type[Any]
    dimension_columns: tuple[str, ...]
    metric_columns: tuple[str, ...]
    column_kinds: Mapping[str, str]

    @property
    def groupable_columns(self) -> tuple[str, ...]:
        """Columns a caller may group by: the property plus this report's dimensions.

        Metrics are deliberately absent. Grouping by a metric is not a security
        problem but a correctness one — it silently changes what the summed
        number means.
        """
        return (PROPERTY_COLUMN, *self.dimension_columns)

    def resolve_group_by(self, name: str) -> InstrumentedAttribute[Any]:
        """Return the mapped column for *name*.

        Raises:
            ValueError: *name* is not one of :attr:`groupable_columns`. The
                unknown value is echoed back **quoted, never executed** — this
                is the branch a ``"country; DROP TABLE …"`` argument takes.
        """
        key = (name or "").strip()
        if key not in self.groupable_columns:
            raise ValueError(
                f"'{name}' is not a groupable column of report '{self.name}'. "
                f"Choose one of: {', '.join(self.groupable_columns)}."
            )
        return getattr(self.model, key)


def _build_binding(spec: GA4ReportSpec) -> ReportBinding:
    """Derive a binding from a collector report spec, verifying it against the model.

    Raises:
        RuntimeError: the spec names a column the fact table does not have. That
            is drift between the collector and storage, and it must stop the
            import — discovering it at query time means a user's question is the
            error report.
    """
    model = _GA4_MODELS_BY_REPORT[spec.name]
    mapped = set(sa_inspect(model).columns.keys())
    kinds: dict[str, str] = {PROPERTY_COLUMN: "id"}
    for ga4_field in spec.fields:
        if ga4_field.column not in mapped:
            raise RuntimeError(
                f"GA4 report '{spec.name}' declares column '{ga4_field.column}', "
                f"which {model.__tablename__} does not have"
            )
        kinds[ga4_field.column] = _DATA_GATE_KINDS.get(ga4_field.kind, "other")
    return ReportBinding(
        name=spec.name,
        description=spec.description,
        grain=spec.grain,
        model=model,
        dimension_columns=tuple(f.column for f in spec.dimensions),
        metric_columns=tuple(f.column for f in spec.metrics),
        column_kinds=kinds,
    )


#: The GA4 report allow-list, derived from the collector's own specs.
REPORT_BINDINGS: dict[str, ReportBinding] = {
    spec.name: _build_binding(spec) for spec in GA4_REPORTS
}

#: ``Connection.source_type`` -> report catalogue. A vendor absent from this map
#: has no collected tables yet, and the agent says so rather than inventing one.
VENDOR_CATALOGUES: Mapping[str, Mapping[str, ReportBinding]] = {"ga4": REPORT_BINDINGS}

#: Display names for the vendors above (kept local so the agent has no reason to
#: import a service module).
VENDOR_LABELS: Mapping[str, str] = {
    "ga4": "Google Analytics 4",
    "appstore": "App Store Connect",
    "googleplay": "Google Play",
}


def resolve_report(
    name: str,
    catalogue: Mapping[str, ReportBinding] | None = None,
) -> ReportBinding:
    """Look *name* up in *catalogue* (default: GA4).

    Raises:
        ValueError: no such report. The caller's string never reaches SQL.
    """
    bindings = REPORT_BINDINGS if catalogue is None else catalogue
    binding = bindings.get((name or "").strip())
    if binding is None:
        raise ValueError(
            f"unknown report '{name}'. Available reports: {', '.join(sorted(bindings))}."
        )
    return binding


# ---------------------------------------------------------------------------
# Period arithmetic
# ---------------------------------------------------------------------------


def _parse_date(raw: Any, field_name: str) -> dt.date:
    """Parse an ISO date, or raise with a message naming the offending field."""
    if isinstance(raw, dt.date) and not isinstance(raw, dt.datetime):
        return raw
    text = str(raw or "").strip()
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO date of the form YYYY-MM-DD, got {raw!r}"
        ) from exc


def _month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _next_month(day: dt.date) -> dt.date:
    return (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def expected_periods(grain: str, start: dt.date, end: dt.date) -> list[str]:
    """Every period key between *start* and *end* inclusive, ascending.

    Daily periods are ``YYYY-MM-DD``; monthly are ``YYYY-MM``. Both sort
    lexicographically, which is why the journal can store them as text.

    Raises:
        ValueError: the range is inverted, or longer than
            :data:`MAX_WINDOW_PERIODS`.
    """
    if end < start:
        raise ValueError(f"date_from ({start.isoformat()}) is after date_to ({end.isoformat()})")

    periods: list[str] = []
    if grain == "monthly":
        cursor = _month_start(start)
        limit = _month_start(end)
        while cursor <= limit:
            periods.append(cursor.strftime("%Y-%m"))
            if len(periods) > MAX_WINDOW_PERIODS:
                break
            cursor = _next_month(cursor)
    else:
        cursor = start
        while cursor <= end:
            periods.append(cursor.isoformat())
            if len(periods) > MAX_WINDOW_PERIODS:
                break
            cursor += dt.timedelta(days=1)

    if len(periods) > MAX_WINDOW_PERIODS:
        raise ValueError(
            f"window spans more than {MAX_WINDOW_PERIODS} periods — narrow the date range"
        )
    return periods


def _period_to_date(period: str, grain: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(period if grain != "monthly" else f"{period}-01")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Result / run state
# ---------------------------------------------------------------------------


@dataclass
class AnalyticsResult(AgentResult):
    """What the analytics agent hands back to the orchestrator.

    ``answer`` is what the user sees (model text **plus** the deterministic
    caveats); ``raw_answer`` is the model's text alone, kept so
    :meth:`~app.agents.validation.AgentResultValidator.validate_analytics_result`
    can ask "did the model state a number?" without matching digits inside the
    caveats it would then be judging.
    """

    answer: str = ""
    raw_answer: str = ""
    caveats: list[str] = field(default_factory=list)
    #: Periods inside a queried window that are missing or failed — the exact
    #: set the answer is *not* allowed to imply it measured.
    pending_periods: list[str] = field(default_factory=list)
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    #: Last successful read, for the viz agent.
    report: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False


@dataclass
class _Window:
    """One ``query_report`` window, remembered so the caveats can be recomputed."""

    report: str
    start: str
    end: str
    missing: list[str]
    failed: list[str]
    last_error: str | None
    #: ``"{period}: {caveat}"`` for periods the collector stored as ``ok`` while
    #: the *vendor* only handed over part of them (``AnalyticsReport.truncated``,
    #: journalled as an ``error`` on an ``ok`` row). Distinct from
    #: ``missing``/``failed``: the numbers are real, they are just not all of
    #: them, so this never means the period is absent from the totals.
    degraded: list[str] = field(default_factory=list)


@dataclass
class _RunState:
    """Per-run scratch space. Never stored on the agent — instances are shared."""

    connection_id: str
    source_name: str
    catalogue: Mapping[str, ReportBinding]
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    windows: list[_Window] = field(default_factory=list)
    gate_errors: list[str] = field(default_factory=list)
    gate_warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    report: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)

    @property
    def pending_periods(self) -> list[str]:
        pending: set[str] = set()
        for window in self.windows:
            pending.update(window.missing)
            pending.update(window.failed)
        return sorted(pending)


SessionFactory = Callable[[], Any]


# ---------------------------------------------------------------------------
# LLM tools
# ---------------------------------------------------------------------------


LIST_REPORTS_TOOL = Tool(
    name="list_reports",
    description=(
        "List the reports this analytics connection can be asked about, with "
        "how much of each has actually been collected."
    ),
    parameters=[],
)

QUERY_REPORT_TOOL = Tool(
    name="query_report",
    description=(
        "Read one report over a date window. Metrics are summed over the window "
        "and over the connection's properties. The result also states which "
        "periods in the window are collected and which are not."
    ),
    parameters=[
        ToolParameter(name="report", type="string", description="Report name"),
        ToolParameter(name="date_from", type="string", description="YYYY-MM-DD, inclusive"),
        ToolParameter(name="date_to", type="string", description="YYYY-MM-DD, inclusive"),
        ToolParameter(
            name="group_by",
            type="string",
            description=(
                "One of the report's dimensions (or property_id). Omit to get one "
                "row per date and dimension combination."
            ),
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description=f"Maximum rows (1..{MAX_ROW_LIMIT}, default {DEFAULT_ROW_LIMIT})",
            required=False,
        ),
    ],
)

COVERAGE_TOOL = Tool(
    name="coverage",
    description=(
        "Report collection state for one report: the latest collected period, "
        "how many periods are on file, which failed and the last error. Use it "
        "to tell 'collected as zero' apart from 'never collected'."
    ),
    parameters=[ToolParameter(name="report", type="string", description="Report name")],
)

ANALYTICS_TOOLS: tuple[Tool, ...] = (LIST_REPORTS_TOOL, QUERY_REPORT_TOOL, COVERAGE_TOOL)


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class AnalyticsAgent(BaseAgent):
    """Answers questions from the collected analytics fact tables."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        *,
        session_factory: SessionFactory | None = None,
        answer_gate: Any = None,
        max_iterations: int | None = None,
    ) -> None:
        """
        Args:
            llm_router: Router for the tool loop; a default one is built lazily.
            session_factory: Zero-arg callable returning an async-context-manager
                session. Defaults to the app factory, resolved at call time so a
                test (or a re-bound engine) is honoured.
            answer_gate: Optional object with an async ``evaluate(...)`` —
                :class:`~app.agents.result_validation.AnswerQualityGate` in
                production. Injected so the gate can be exercised without an LLM.
            max_iterations: Tool-loop budget. Defaults to
                ``settings.max_mcp_iterations``, the shared external-source loop
                budget, until analytics gets a knob of its own.
        """
        self._llm = llm_router or LLMRouter()
        self._session_factory = session_factory
        self._answer_gate = answer_gate
        self._max_iterations = max_iterations

    @property
    def name(self) -> str:
        return "analytics"

    # -- plumbing ------------------------------------------------------

    def _session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        from app.models import base as base_mod

        return base_mod.async_session_factory()

    @property
    def max_iterations(self) -> int:
        return self._max_iterations or settings.max_mcp_iterations

    def _build_answer_gate(self) -> Any:
        if self._answer_gate is not None:
            return self._answer_gate
        from app.agents.answer_validator import AnswerValidator
        from app.agents.result_validation import AnswerQualityGate

        return AnswerQualityGate(AnswerValidator(self._llm))

    # -- entry point ---------------------------------------------------

    async def run(
        self,
        context: AgentContext,
        *,
        connection_id: str = "",
        question: str | None = None,
        source_name: str = "Analytics Source",
        source_type: str = "ga4",
        report: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        **_kwargs: Any,
    ) -> AnalyticsResult:
        """Answer *question* from the rows collected for *connection_id*."""
        catalogue = VENDOR_CATALOGUES.get(source_type)
        if not catalogue:
            label = VENDOR_LABELS.get(source_type, source_type)
            # Refused before the first token is spent: a vendor with no tables
            # cannot be answered from, and pretending otherwise is the exact
            # failure this agent exists to prevent.
            return AnalyticsResult(
                status="error",
                error=(
                    f"No collected reports exist for source type '{source_type}' "
                    f"({label}) yet, so there is nothing to answer from."
                ),
            )

        if not connection_id:
            return AnalyticsResult(
                status="error",
                error="No analytics connection was supplied.",
            )

        state = _RunState(connection_id=connection_id, source_name=source_name, catalogue=catalogue)
        user_question = question or context.user_question
        messages = self._initial_messages(
            state,
            source_type=source_type,
            user_question=user_question,
            report=report,
            date_from=date_from,
            date_to=date_to,
        )

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        budget = self._llm.get_context_window(context.model)

        for iteration in range(self.max_iterations):
            messages, _ = trim_loop_messages(messages, budget)
            try:
                llm_resp: LLMResponse = await llm_call_with_retry(
                    self._llm,
                    messages=messages,
                    tools=list(ANALYTICS_TOOLS),
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                    component="analytics_agent",
                )
            except Exception:
                logger.exception("AnalyticsAgent LLM call failed (iter %d)", iteration)
                return AnalyticsResult(
                    status="error",
                    error="LLM call failed during the analytics tool loop",
                    token_usage=total_usage,
                    tool_calls_made=state.tool_calls_made,
                )
            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                return await self._finalise(
                    state,
                    context,
                    raw_answer=llm_resp.content or "",
                    token_usage=total_usage,
                )

            messages.append(
                Message(
                    role="assistant",
                    content=llm_resp.content or "",
                    tool_calls=llm_resp.tool_calls,
                )
            )
            for tc in llm_resp.tool_calls:
                messages.append(await self._execute_tool_call(state, tc))

        # Budget exhausted without a final answer. This is a silent failure, not
        # a success: returning the partial tool output as prose would present
        # half a gather as a conclusion.
        return AnalyticsResult(
            status="no_result",
            answer="Reached maximum iterations for analytics tool calls.",
            token_usage=total_usage,
            tool_calls_made=state.tool_calls_made,
        )

    # -- loop helpers --------------------------------------------------

    def _initial_messages(
        self,
        state: _RunState,
        *,
        source_type: str,
        user_question: str,
        report: str | None,
        date_from: str | None,
        date_to: str | None,
    ) -> list[Message]:
        catalogue_text = "\n".join(
            f"- {binding.name} ({binding.grain}): {binding.description}"
            for binding in state.catalogue.values()
        )
        system_prompt = build_analytics_system_prompt(
            source_name=state.source_name,
            vendor_label=VENDOR_LABELS.get(source_type, source_type),
            report_catalogue=catalogue_text,
            current_datetime=get_current_datetime_str(),
        )
        hints = [
            f"{label}: {value}"
            for label, value in (
                ("report", report),
                ("date_from", date_from),
                ("date_to", date_to),
            )
            if value
        ]
        user_content = user_question
        if hints:
            user_content += "\n\n(Caller hints — " + "; ".join(hints) + ")"
        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_content),
        ]

    async def _execute_tool_call(self, state: _RunState, tc: ToolCall) -> Message:
        """Run one tool call and return the ``tool`` message carrying its result."""
        arguments = tc.arguments or {}
        try:
            result_text = await self._run_tool(state, tc.name, arguments)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Analytics tool %s failed", tc.name)
            result_text = f"Error running tool {tc.name}: {exc}"

        if len(result_text) > TOOL_RESULT_CHARS:
            result_text = (
                result_text[:TOOL_RESULT_CHARS]
                + f"\n... (truncated, {len(result_text)} chars total)"
            )
        state.tool_calls_made.append(
            {
                "tool": tc.name,
                "arguments": arguments,
                "result_preview": result_text[:TOOL_PREVIEW_CHARS],
            }
        )
        return Message(role="tool", content=result_text, tool_call_id=tc.id, name=tc.name)

    async def _run_tool(self, state: _RunState, name: str, arguments: Mapping[str, Any]) -> str:
        if name == "list_reports":
            return await self._tool_list_reports(state)
        if name == "coverage":
            return await self._tool_coverage(state, arguments)
        if name == "query_report":
            return await self._tool_query_report(state, arguments)
        return (
            f"Error: unknown tool '{name}'. Available tools: list_reports, query_report, coverage."
        )

    # -- tools ---------------------------------------------------------

    async def _tool_list_reports(self, state: _RunState) -> str:
        async with self._session() as session:
            lines = [f'Reports available on "{state.source_name}":', ""]
            for binding in state.catalogue.values():
                statuses = await self._period_statuses(session, state, binding.name)
                on_file = sorted(p for p, (s, _e) in statuses.items() if s in DONE_STATUSES)
                failed = sorted(p for p, (s, _e) in statuses.items() if s == "failed")
                if on_file:
                    coverage = f"{len(on_file)} period(s) on file, latest {on_file[-1]}"
                else:
                    coverage = "nothing on file yet"
                if failed:
                    coverage += f", {len(failed)} failed"
                lines.append(f"- {binding.name} ({binding.grain}): {coverage}")
                lines.append(f"  {binding.description}")
        return "\n".join(lines)

    async def _tool_coverage(self, state: _RunState, arguments: Mapping[str, Any]) -> str:
        try:
            binding = resolve_report(str(arguments.get("report", "")), state.catalogue)
        except ValueError as exc:
            return f"Error: {exc}"

        async with self._session() as session:
            statuses = await self._period_statuses(session, state, binding.name)

        on_file = sorted(p for p, (s, _e) in statuses.items() if s in DONE_STATUSES)
        failed = sorted(p for p, (s, _e) in statuses.items() if s == "failed")
        last_error = self._last_error(statuses)

        lines = [f"Coverage for report '{binding.name}' on \"{state.source_name}\":"]
        if on_file:
            lines.append(f"- latest collected period: {on_file[-1]}")
            lines.append(f"- periods on file: {len(on_file)} (from {on_file[0]} to {on_file[-1]})")
        else:
            lines.append("- latest collected period: none on file yet")
            lines.append("- periods on file: 0")
        gaps = self._gaps(binding, statuses)
        lines.append(f"- failed periods: {self._render_periods(failed)}")
        lines.append(f"- gaps inside the collected span: {self._render_periods(gaps)}")
        lines.append(f"- last error: {last_error or 'none'}")
        lines.append(
            "- anything after the latest collected period has no data on file; "
            "that is a gap in collection, not a measured zero."
        )
        return "\n".join(lines)

    async def _tool_query_report(self, state: _RunState, arguments: Mapping[str, Any]) -> str:
        try:
            binding = resolve_report(str(arguments.get("report", "")), state.catalogue)
            start = _parse_date(arguments.get("date_from"), "date_from")
            end = _parse_date(arguments.get("date_to"), "date_to")
            periods = expected_periods(binding.grain, start, end)
            group_names, group_columns = self._resolve_grouping(binding, arguments.get("group_by"))
            limit = self._resolve_limit(arguments.get("limit"))
        except ValueError as exc:
            # Every caller-supplied string lands here or nowhere. Nothing below
            # this point runs, so nothing unvalidated reaches a statement.
            return f"Error: {exc}"

        async with self._session() as session:
            rows, truncated = await self._select_rows(
                session, state, binding, group_columns, start, end, limit
            )
            statuses = await self._period_statuses(session, state, binding.name)

        columns = [*group_names, *binding.metric_columns]
        missing = [p for p in periods if p not in statuses]
        failed = [p for p in periods if statuses.get(p, ("", None))[0] == "failed"]
        # A collected period can still carry a caveat: the collect service writes
        # the vendor's ``degraded`` sentence into ``error`` on an otherwise ``ok``
        # row. Reading only ``missing``/``failed`` drops it, and the window then
        # reports itself complete while a period inside it was truncated.
        degraded = [
            f"{p}: {statuses[p][1]}"
            for p in periods
            if statuses.get(p, ("", None))[0] in DONE_STATUSES and statuses[p][1]
        ]
        window = _Window(
            report=binding.name,
            start=start.isoformat(),
            end=end.isoformat(),
            missing=missing,
            failed=failed,
            last_error=self._last_error({p: statuses[p] for p in failed if p in statuses}),
            degraded=degraded,
        )
        state.windows.append(window)

        gate_outcome = self._run_data_gate(binding, columns, rows, truncated)
        header = (
            f"Report '{binding.name}' from {start.isoformat()} to {end.isoformat()}, "
            f"grouped by {', '.join(group_names)}."
        )
        coverage_lines = self._window_coverage_lines(window, periods)

        if not gate_outcome.passed:
            state.gate_errors.extend(gate_outcome.errors)
            return "\n".join(
                [
                    header,
                    *coverage_lines,
                    "",
                    "DATA QUALITY BLOCK — the collected rows contain impossible "
                    "values and are withheld: " + "; ".join(gate_outcome.errors),
                ]
            )

        state.gate_warnings.extend(gate_outcome.warnings)
        state.report = binding.name
        state.columns = columns
        state.rows = rows
        state.truncated = state.truncated or truncated

        body = self._render_rows(columns, rows, truncated, limit)
        parts = [header, *coverage_lines, "", body]
        if gate_outcome.warnings:
            parts.append("Data-quality warnings: " + "; ".join(gate_outcome.warnings))
        return "\n".join(parts)

    # -- query building ------------------------------------------------

    def _resolve_grouping(
        self,
        binding: ReportBinding,
        raw_group_by: Any,
    ) -> tuple[list[str], list[InstrumentedAttribute[Any]]]:
        """Resolve ``group_by`` to real columns, defaulting to every dimension."""
        text = str(raw_group_by).strip() if raw_group_by not in (None, "") else ""
        if not text:
            names = list(binding.dimension_columns)
        else:
            # One name only: a comma-separated list is exactly the shape an
            # injection attempt takes, and multi-column grouping has no caller.
            binding.resolve_group_by(text)
            names = [text]
        return names, [getattr(binding.model, name) for name in names]

    @staticmethod
    def _resolve_limit(raw_limit: Any) -> int:
        if raw_limit in (None, ""):
            return DEFAULT_ROW_LIMIT
        try:
            value = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"limit must be a whole number, got {raw_limit!r}") from exc
        return max(1, min(value, MAX_ROW_LIMIT))

    async def _select_rows(
        self,
        session: AsyncSession,
        state: _RunState,
        binding: ReportBinding,
        group_columns: Sequence[InstrumentedAttribute[Any]],
        start: dt.date,
        end: dt.date,
        limit: int,
    ) -> tuple[list[list[Any]], bool]:
        """Run the aggregate read. Every value below is a bound parameter."""
        metric_columns = [
            func.sum(getattr(binding.model, metric)).label(metric)
            for metric in binding.metric_columns
        ]
        stmt = (
            select(*group_columns, *metric_columns)
            .where(
                binding.model.connection_id == state.connection_id,
                binding.model.date >= start,
                binding.model.date <= end,
            )
            .group_by(*group_columns)
        )
        if "date" in {column.key for column in group_columns}:
            stmt = stmt.order_by(binding.model.date.asc())
        elif metric_columns:
            # No date axis, so rank by the headline metric: when the row cap
            # bites, the rows that survive should be the ones that matter.
            stmt = stmt.order_by(metric_columns[0].desc())
        else:  # pragma: no cover - every current report declares metrics
            stmt = stmt.order_by(*group_columns)

        # limit + 1 so "capped" is observed rather than inferred.
        result = await session.execute(stmt.limit(limit + 1))
        rows = [list(row) for row in result.all()]
        truncated = len(rows) > limit
        return rows[:limit], truncated

    @staticmethod
    def _run_data_gate(
        binding: ReportBinding,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        truncated: bool,
    ) -> Any:
        """Run DataGate value-range hard checks with our own column semantics.

        The keyword heuristic does not know that ``sessions`` is a count, so a
        negative session total would sail through. We do know — the report spec
        declares every field's kind — so the classifier is injected rather than
        guessed. ``data_gate_hard_checks_enabled`` still decides fail vs warn.
        """
        query_result = QueryResult(
            columns=list(columns),
            rows=[list(row) for row in rows],
            row_count=len(rows),
            truncated=truncated,
        )
        gate = DataGate(
            column_semantic_classifier=lambda cols, _sample: {
                col: binding.column_kinds.get(col, "other") for col in cols
            }
        )
        return gate.check_query_result(query_result)

    # -- journal reads -------------------------------------------------

    @staticmethod
    async def _period_statuses(
        session: AsyncSession,
        state: _RunState,
        report: str,
    ) -> dict[str, tuple[str, str | None]]:
        """``{period: (status, error)}`` for one report of this connection."""
        rows = (
            await session.execute(
                select(
                    AnalyticsImport.period,
                    AnalyticsImport.status,
                    AnalyticsImport.error,
                ).where(
                    AnalyticsImport.connection_id == state.connection_id,
                    AnalyticsImport.report == report,
                )
            )
        ).all()
        return {period: (status, error) for period, status, error in rows}

    @staticmethod
    def _last_error(statuses: Mapping[str, tuple[str, str | None]]) -> str | None:
        """The newest recorded error, prefixed with its period."""
        failures = sorted(
            (period, error) for period, (status, error) in statuses.items() if status == "failed"
        )
        for period, error in reversed(failures):
            if error:
                return f"{error} ({period})"
        return None

    @staticmethod
    def _gaps(
        binding: ReportBinding,
        statuses: Mapping[str, tuple[str, str | None]],
    ) -> list[str]:
        """Periods with no journal row *between* the first and last on file.

        A hole inside the collected span is a different animal from "we have not
        got that far yet", and only the former means a backfill silently skipped
        something.
        """
        on_file = sorted(p for p, (status, _e) in statuses.items() if status in DONE_STATUSES)
        if len(on_file) < 2:
            return []
        start = _period_to_date(on_file[0], binding.grain)
        end = _period_to_date(on_file[-1], binding.grain)
        if start is None or end is None:
            return []
        try:
            span = expected_periods(binding.grain, start, end)
        except ValueError:
            return []
        return [period for period in span if period not in statuses]

    # -- rendering -----------------------------------------------------

    @staticmethod
    def _render_periods(periods: Sequence[str]) -> str:
        if not periods:
            return "none"
        head = list(periods[:MAX_NAMED_PERIODS])
        text = ", ".join(head)
        if len(periods) > MAX_NAMED_PERIODS:
            text += f" … and {len(periods) - MAX_NAMED_PERIODS} more"
        return text

    @staticmethod
    def _render_degraded(entries: Sequence[str]) -> str:
        """Vendor caveats, capped like the period lists so one line stays a line.

        Each entry already opens with its period, so truncating the list still
        leaves every rendered caveat attributable to a date. The vendor's own
        sentence ends in a full stop; it is dropped here so the surrounding
        prose punctuates the line rather than doubling up.
        """
        head = [entry.strip().removesuffix(".") for entry in entries[:MAX_NAMED_PERIODS]]
        text = "; ".join(head)
        if len(entries) > MAX_NAMED_PERIODS:
            text += f" … and {len(entries) - MAX_NAMED_PERIODS} more"
        return text

    @staticmethod
    def _cell(value: Any) -> str:
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        if isinstance(value, (dt.date, dt.datetime)):
            return value.isoformat()
        return "" if value is None else str(value)

    def _window_coverage_lines(self, window: _Window, periods: Sequence[str]) -> list[str]:
        """The honesty block, printed *before* the rows so it cannot be missed."""
        lines: list[str] = []
        if window.missing:
            lines.append(
                "NOT COLLECTED: "
                + self._render_periods(window.missing)
                + " — no data has ever been collected for "
                + ("these periods" if len(window.missing) > 1 else "this period")
                + ", so the value is unknown, NOT zero."
            )
        if window.failed:
            failed_line = "COLLECTION FAILED: " + self._render_periods(window.failed)
            if window.last_error:
                failed_line += f" (last error: {window.last_error})"
            failed_line += " — these periods are missing from the totals below."
            lines.append(failed_line)
        if window.degraded:
            lines.append(
                "PARTIAL VENDOR DATA: "
                + self._render_degraded(window.degraded)
                + " — the vendor truncated "
                + ("these periods" if len(window.degraded) > 1 else "this period")
                + " at collect time, so the values below are based on a partial "
                "vendor response: they are real, but lower than the true total."
            )
        # Only when nothing above fired: this sentence and any caveat line are a
        # contradiction, and the contradiction is what tells a user a fraction of
        # a number is the number.
        if not lines:
            lines.append(
                f"Coverage: all {len(periods)} period(s) in this window have been "
                "collected, so the values below are real measurements."
            )
        return lines

    def _render_rows(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        truncated: bool,
        limit: int,
    ) -> str:
        if not rows:
            return "Rows: 0 (no rows on file for this window)."
        lines = [f"Rows: {len(rows)}", " | ".join(columns)]
        lines.extend(" | ".join(self._cell(value) for value in row) for row in rows)
        if truncated:
            lines.append(
                f"TRUNCATED: more rows exist than the {limit}-row cap — totals over "
                "these rows are a lower bound."
            )
        return "\n".join(lines)

    # -- the gates -----------------------------------------------------

    async def _finalise(
        self,
        state: _RunState,
        context: AgentContext,
        *,
        raw_answer: str,
        token_usage: dict[str, int],
    ) -> AnalyticsResult:
        """Gates, in spec §3.3 order: DataGate → partial → freshness → quality."""
        if state.gate_errors:
            # 1. Hard-check block. The model's text is discarded rather than
            #    caveated: it was composed from impossible numbers.
            return AnalyticsResult(
                status="error",
                answer="",
                error="Blocked by data-quality checks: " + "; ".join(state.gate_errors),
                token_usage=token_usage,
                tool_calls_made=state.tool_calls_made,
                pending_periods=state.pending_periods,
            )

        caveats: list[str] = []
        # 2. Truncation / partial-data caveats.
        caveats.extend(self._partial_caveats(state))
        if state.truncated:
            caveats.append(
                "PARTIAL DATA: the row cap was reached, so totals above are a lower bound."
            )
        caveats.extend(state.gate_warnings)

        # 3. Freshness.
        freshness = await self._freshness_lines(state)

        answer = self._compose(raw_answer, caveats, freshness)

        # 4. Answer-quality gate.
        gate_note = await self._answer_quality_note(context, answer)
        if gate_note:
            caveats.append(gate_note)
            answer = self._compose(raw_answer, caveats, freshness)

        return AnalyticsResult(
            status="success",
            answer=answer,
            raw_answer=raw_answer,
            caveats=caveats,
            pending_periods=state.pending_periods,
            token_usage=token_usage,
            tool_calls_made=state.tool_calls_made,
            report=state.report,
            columns=state.columns,
            rows=state.rows,
            truncated=state.truncated,
        )

    def _partial_caveats(self, state: _RunState) -> list[str]:
        caveats: list[str] = []
        for window in state.windows:
            caveats.extend(self._window_partial_caveats(window))
        return caveats

    def _window_partial_caveats(self, window: _Window) -> list[str]:
        """Absent periods and truncated ones, kept apart.

        Two different failures of honesty need two different sentences: a missing
        or failed period is *not in* the totals, while a vendor-truncated one is
        in them and is simply short. Folding them together would either invite
        the reader to add back a period that is already counted, or imply a
        period that never arrived is partly represented.
        """
        caveats: list[str] = []
        if window.missing or window.failed:
            clauses: list[str] = []
            if window.missing:
                clauses.append(
                    f"{self._render_periods(window.missing)} "
                    + ("have" if len(window.missing) > 1 else "has")
                    + " not been collected yet"
                )
            if window.failed:
                clause = f"collection failed for {self._render_periods(window.failed)}"
                if window.last_error:
                    clause += f" (last error: {window.last_error})"
                clauses.append(clause)
            caveats.append(
                f"PARTIAL DATA: report '{window.report}' over "
                f"{window.start}..{window.end} is incomplete — "
                + "; ".join(clauses)
                + ". Those periods are excluded from the numbers above and are "
                "NOT zeros."
            )
        if window.degraded:
            caveats.append(
                f"PARTIAL DATA: report '{window.report}' over "
                f"{window.start}..{window.end} is based on a partial vendor "
                "response — " + self._render_degraded(window.degraded) + ". Those "
                "periods ARE counted above, but the vendor only handed over part "
                "of each, so the numbers are real and are a lower bound — NOT a "
                "complete measurement."
            )
        return caveats

    async def _freshness_lines(self, state: _RunState) -> list[str]:
        """One line per queried report naming how far collection actually got."""
        reports = list(dict.fromkeys(window.report for window in state.windows))
        if not reports:
            return []
        lines: list[str] = []
        async with self._session() as session:
            for report in reports:
                statuses = await self._period_statuses(session, state, report)
                on_file = sorted(p for p, (s, _e) in statuses.items() if s in DONE_STATUSES)
                if on_file:
                    lines.append(
                        f"Freshness: report '{report}' is collected through {on_file[-1]}. "
                        "Analytics vendors settle their data with a lag, so the most "
                        "recent day or two is usually still absent by design."
                    )
                else:
                    lines.append(
                        f"Freshness: report '{report}' has never been collected for this "
                        "connection, so there is nothing on file for any period."
                    )
        return lines

    async def _answer_quality_note(self, context: AgentContext, answer: str) -> str | None:
        """Run the answer-quality gate; a non-accept verdict becomes a caveat.

        Fail-open, matching the orchestrator: a gate that errors must not lose a
        real answer, and the verdict is advisory, not a veto.
        """
        if not settings.answer_validator_enabled or not answer.strip():
            return None
        try:
            gate = self._build_answer_gate()
            directive = await gate.evaluate(
                question=context.user_question,
                answer=answer,
                preferred_provider=context.preferred_provider,
                model=context.model,
            )
        except Exception:
            logger.warning("Analytics answer-quality gate failed", exc_info=True)
            return None
        if getattr(directive, "action", "accept") == "accept":
            return None
        return f"ANSWER QUALITY ({directive.action}): {directive.reason}"

    @staticmethod
    def _compose(raw_answer: str, caveats: Sequence[str], freshness: Sequence[str]) -> str:
        parts = [raw_answer.strip()] if raw_answer.strip() else []
        parts.extend(f"⚠️ {caveat}" for caveat in caveats)
        parts.extend(freshness)
        return "\n\n".join(parts)
