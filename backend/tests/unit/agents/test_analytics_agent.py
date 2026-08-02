"""T8 — :class:`~app.agents.analytics_agent.AnalyticsAgent` (spec §3.3).

The agent answers from the **local** GA4 fact tables, so every test here builds
a real (in-memory) database and a scripted LLM. Nothing touches a vendor.

The load-bearing test is :class:`TestEmptyVersusZero`. Two questions that look
identical to a naive implementation —

* "how many sessions on the 10th?" where the 10th *was* collected and the
  vendor reported 0, and
* "how many sessions on the 11th?" where the 11th was **never collected**

— must produce different answers. An implementation that reads "no rows" as
"zero" answers "0 sessions" to both, which is a fabricated number dressed as a
measurement. The journal is the only thing that can tell them apart, which is
why the coverage lookup is consulted rather than the row count.

The scripted LLM deliberately *echoes* its tool results instead of inventing
prose: that keeps the assertions about what the agent's tools and gates
actually produced, not about a fake model's wording.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.agents.analytics_agent import (
    REPORT_BINDINGS,
    AnalyticsAgent,
    AnalyticsResult,
    resolve_report,
)
from app.agents.base import AgentContext
from app.agents.validation import AgentResultValidator
from app.config import settings
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall
from app.models.analytics_ga4 import GA4GeoDaily, GA4OverviewDaily
from app.models.analytics_import import AnalyticsImport
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.project import Project

USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

PROPERTY_ID = "294380179"
OTHER_PROPERTY_ID = "999999999"

PRUNED_DAY = "2026-07-09"
COLLECTED_ZERO_DAY = "2026-07-10"
NEVER_COLLECTED_DAY = "2026-07-11"
FAILED_DAY = "2026-07-12"
NEGATIVE_DAY = "2026-07-13"

#: What a model recites when it answers an analytics question from prior
#: knowledge instead of from the collected rows.
FABRICATED = "July had roughly 12,400 sessions."


# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Fake ``LLMRouter``: issues scripted tool calls, then echoes the results.

    Turn 1 emits ``tool_calls``; turn 2 answers with the concatenated tool
    output. Echoing (rather than inventing prose) means every assertion in this
    module is about what the agent's own tools said.
    """

    def __init__(self, tool_calls: list[ToolCall], *, repeat: bool = False) -> None:
        self._tool_calls = tool_calls
        self._repeat = repeat
        self.call_count = 0
        self.tool_specs: list[Any] = []

    def get_context_window(self, _model: str | None = None) -> int:
        return 100_000

    async def complete(
        self,
        *,
        messages: list[Any],
        tools: list[Any] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        if tools:
            self.tool_specs = tools
        if self._repeat or self.call_count == 1:
            return LLMResponse(content="", tool_calls=list(self._tool_calls), usage=USAGE)
        echoed = "\n".join(m.content for m in messages if m.role == "tool")
        return LLMResponse(content=f"Here is what was collected:\n{echoed}", usage=USAGE)


class TurnScriptedLLM:
    """Fake ``LLMRouter`` driven by an explicit turn-by-turn script.

    :class:`ScriptedLLM` always opens with tool calls; the grounding tests need
    the opposite — a model that answers straight away — so every turn is spelled
    out here. The last turn repeats if the loop runs longer than the script.
    """

    def __init__(self, turns: list[LLMResponse]) -> None:
        self._turns = list(turns)
        self.call_count = 0
        self.last_messages: list[Any] = []

    def get_context_window(self, _model: str | None = None) -> int:
        return 100_000

    async def complete(
        self,
        *,
        messages: list[Any],
        tools: list[Any] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_messages = list(messages)
        return self._turns[min(self.call_count - 1, len(self._turns) - 1)]

    @property
    def injected_system_messages(self) -> list[str]:
        """System messages the agent added after the initial prompt pair."""
        return [m.content for m in self.last_messages[1:] if m.role == "system"]


class ExplodingSession:
    """A session whose every SQL execution is a test failure.

    Used to prove a rejected argument never reaches the database: if validation
    lets a hostile string through, ``execute`` raises and the assertion changes.
    """

    def __init__(self) -> None:
        self.executed = False

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        self.executed = True
        raise AssertionError("SQL was executed with an unvalidated argument")

    async def __aenter__(self) -> ExplodingSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


def _tool_call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"tc-{name}", name=name, arguments=dict(arguments))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def connection_id(sm) -> str:
    async with sm() as session:
        project = Project(name=f"p-{uuid.uuid4().hex[:6]}")
        session.add(project)
        await session.commit()
        conn = Connection(project_id=project.id, name="GA4 prod", source_type="ga4")
        session.add(conn)
        await session.commit()
        return conn.id


@pytest_asyncio.fixture
async def other_connection_id(sm, connection_id: str) -> str:
    """A second analytics connection in the same project.

    Every other fixture in this module has exactly one connection, which means
    dropping a ``connection_id ==`` predicate from either read would go
    unnoticed. This one is the control for :class:`TestTenantIsolation`.
    """
    async with sm() as session:
        owner = await session.get(Connection, connection_id)
        assert owner is not None
        conn = Connection(project_id=owner.project_id, name="GA4 staging", source_type="ga4")
        session.add(conn)
        await session.commit()
        return conn.id


async def _journal(
    sm, connection_id: str, report: str, period: str, status: str, **kw: Any
) -> None:
    async with sm() as session:
        session.add(
            AnalyticsImport(
                connection_id=connection_id,
                report=report,
                period=period,
                status=status,
                rows_written=kw.get("rows_written", 0),
                error=kw.get("error"),
            )
        )
        await session.commit()


async def _overview_row(sm, connection_id: str, day: str, **metrics: Any) -> None:
    async with sm() as session:
        session.add(
            GA4OverviewDaily(
                connection_id=connection_id,
                property_id=metrics.get("property_id", PROPERTY_ID),
                date=dt.date.fromisoformat(day),
                sessions=metrics.get("sessions", 0),
                active_users=metrics.get("active_users", 0),
                new_users=metrics.get("new_users", 0),
                screen_page_views=metrics.get("screen_page_views", 0),
                event_count=metrics.get("event_count", 0),
                total_revenue=metrics.get("total_revenue", Decimal("0")),
            )
        )
        await session.commit()


async def _geo_row(sm, connection_id: str, day: str, country: str, sessions: int) -> None:
    async with sm() as session:
        session.add(
            GA4GeoDaily(
                connection_id=connection_id,
                property_id=PROPERTY_ID,
                date=dt.date.fromisoformat(day),
                country=country,
                sessions=sessions,
                active_users=sessions,
            )
        )
        await session.commit()


def _context() -> AgentContext:
    tracker = MagicMock(spec=WorkflowTracker)
    tracker.emit = AsyncMock()
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="how many sessions?",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=tracker,
        workflow_id="wf-1",
    )


def _agent(llm: Any, sm: Any, **kwargs: Any) -> AnalyticsAgent:
    return AnalyticsAgent(llm_router=llm, session_factory=sm, **kwargs)


@pytest.fixture(autouse=True)
def _no_answer_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer-quality gate calls an LLM; it gets its own test."""
    monkeypatch.setattr(settings, "answer_validator_enabled", False)


# ---------------------------------------------------------------------------
# Report allow-list
# ---------------------------------------------------------------------------


class TestReportAllowList:
    def test_every_ga4_report_is_bound_to_a_model(self) -> None:
        assert set(REPORT_BINDINGS) == {"overview", "geo", "platform", "trend", "events"}
        for binding in REPORT_BINDINGS.values():
            assert binding.model.__tablename__.startswith("ga4_")

    def test_unknown_report_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown report"):
            resolve_report("ga4_geo_daily; DROP TABLE users--")

    def test_hostile_group_by_is_rejected(self) -> None:
        binding = REPORT_BINDINGS["geo"]
        with pytest.raises(ValueError, match="not a groupable column"):
            binding.resolve_group_by("country; DROP TABLE ga4_geo_daily--")

    def test_metric_columns_are_not_groupable(self) -> None:
        """Grouping by a metric would silently change what the number means."""
        binding = REPORT_BINDINGS["geo"]
        with pytest.raises(ValueError):
            binding.resolve_group_by("sessions")

    def test_legitimate_dimension_resolves_to_a_real_column(self) -> None:
        column = REPORT_BINDINGS["geo"].resolve_group_by("country")
        assert column is GA4GeoDaily.country

    def test_counts_are_classified_for_the_data_gate(self) -> None:
        kinds = REPORT_BINDINGS["overview"].column_kinds
        assert kinds["sessions"] == "count"
        assert kinds["date"] == "date"
        # Revenue can legitimately be negative (refunds) — never a hard "count".
        assert kinds["total_revenue"] != "count"


# ---------------------------------------------------------------------------
# Hostile input never reaches SQL
# ---------------------------------------------------------------------------


class TestHostileArgumentsNeverReachSql:
    async def test_hostile_group_by_is_refused_before_any_query(self) -> None:
        session = ExplodingSession()
        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="geo",
                    date_from="2026-07-01",
                    date_to="2026-07-31",
                    group_by="country; DROP TABLE ga4_geo_daily--",
                )
            ]
        )
        agent = _agent(llm, lambda: session)

        result = await agent.run(_context(), connection_id="conn-1", question="top countries")

        assert session.executed is False
        assert "not a groupable column" in result.tool_calls_made[0]["result_preview"]

    async def test_hostile_report_name_is_refused_before_any_query(self) -> None:
        session = ExplodingSession()
        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="ga4_geo_daily UNION SELECT password FROM users",
                    date_from="2026-07-01",
                    date_to="2026-07-31",
                )
            ]
        )
        agent = _agent(llm, lambda: session)

        result = await agent.run(_context(), connection_id="conn-1", question="anything")

        assert session.executed is False
        assert "unknown report" in result.tool_calls_made[0]["result_preview"]

    async def test_malformed_date_is_refused_before_any_query(self) -> None:
        session = ExplodingSession()
        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from="2026-07-01' OR '1'='1",
                    date_to="2026-07-31",
                )
            ]
        )
        agent = _agent(llm, lambda: session)

        result = await agent.run(_context(), connection_id="conn-1", question="anything")

        assert session.executed is False
        assert "date" in result.tool_calls_made[0]["result_preview"].lower()

    async def test_hostile_group_by_leaves_the_table_intact(self, sm, connection_id: str) -> None:
        """End-to-end: the injection attempt runs against a real database."""
        await _geo_row(sm, connection_id, COLLECTED_ZERO_DAY, "Germany", 12)
        await _journal(sm, connection_id, "geo", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="geo",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                    group_by="country; DROP TABLE ga4_geo_daily--",
                )
            ]
        )
        await _agent(llm, sm).run(_context(), connection_id=connection_id, question="countries")

        async with sm() as session:
            rows = (await session.execute(GA4GeoDaily.__table__.select())).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Empty vs zero — the test that matters most
# ---------------------------------------------------------------------------


class TestEmptyVersusZero:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, sm, connection_id: str) -> None:
        # The 10th was collected and the vendor genuinely reported nothing.
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=0)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        # The 11th has never been collected. No journal row, no fact row.

    async def _answer_for(self, sm, connection_id: str, day: str) -> AnalyticsResult:
        llm = ScriptedLLM(
            [
                _tool_call("query_report", report="overview", date_from=day, date_to=day),
                _tool_call("coverage", report="overview"),
            ]
        )
        return await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question=f"sessions on {day}?"
        )

    async def test_collected_zero_and_never_collected_differ(self, sm, connection_id: str) -> None:
        zero = await self._answer_for(sm, connection_id, COLLECTED_ZERO_DAY)
        missing = await self._answer_for(sm, connection_id, NEVER_COLLECTED_DAY)

        assert zero.answer != missing.answer
        # …and they differ in the way that matters, not merely in the date echoed.
        assert "not collected" in missing.answer.lower()
        assert "not collected" not in zero.answer.lower()

    async def test_collected_zero_reports_a_zero(self, sm, connection_id: str) -> None:
        result = await self._answer_for(sm, connection_id, COLLECTED_ZERO_DAY)

        assert "not collected" not in result.answer.lower()
        assert "0" in result.answer
        assert result.pending_periods == []

    async def test_never_collected_says_so_instead_of_zero(self, sm, connection_id: str) -> None:
        result = await self._answer_for(sm, connection_id, NEVER_COLLECTED_DAY)

        assert "not collected" in result.answer.lower()
        assert NEVER_COLLECTED_DAY in result.answer
        assert result.pending_periods == [NEVER_COLLECTED_DAY]

    async def test_query_report_tool_output_marks_the_gap(self, sm, connection_id: str) -> None:
        """The distinction is visible to the model, not only in the caveat."""
        result = await self._answer_for(sm, connection_id, NEVER_COLLECTED_DAY)
        query_output = next(
            c["result_preview"] for c in result.tool_calls_made if c["tool"] == "query_report"
        )

        assert "NOT COLLECTED" in query_output
        assert NEVER_COLLECTED_DAY in query_output

    async def test_coverage_reports_the_latest_collected_period(
        self, sm, connection_id: str
    ) -> None:
        result = await self._answer_for(sm, connection_id, NEVER_COLLECTED_DAY)
        coverage_output = next(
            c["result_preview"] for c in result.tool_calls_made if c["tool"] == "coverage"
        )

        assert COLLECTED_ZERO_DAY in coverage_output
        assert NEVER_COLLECTED_DAY not in coverage_output.split("latest collected")[0]


# ---------------------------------------------------------------------------
# No answer without a read
# ---------------------------------------------------------------------------


class TestGroundingRequired:
    """An answer composed before any tool read something is prior knowledge.

    The prompt tells the model to answer only from tool results, but the module
    docstring's own rule applies: a guarantee that depends on the model
    complying with an instruction is not a guarantee. So the loop enforces it,
    mirroring the orchestrator's ORCH-T02/T03 pair — re-prompt once, then refuse.
    """

    async def test_immediate_answer_is_reprompted_and_then_refused(
        self, sm, connection_id: str
    ) -> None:
        llm = TurnScriptedLLM(
            [
                LLMResponse(content=FABRICATED, usage=USAGE),
                LLMResponse(content=FABRICATED, usage=USAGE),
            ]
        )

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="how many sessions in July?"
        )

        # Re-prompted exactly once, and the nudge told it to call a tool.
        assert llm.call_count == 2
        assert len(llm.injected_system_messages) == 1
        assert "query_report" in llm.injected_system_messages[0]

        assert result.status == "no_result"
        # The fabricated number never reaches the user, by any field.
        assert "12,400" not in result.answer
        assert "12,400" not in (result.error or "")
        assert FABRICATED not in result.answer
        assert result.pending_periods == []

    async def test_a_refused_answer_never_passes_the_validator(
        self, sm, connection_id: str
    ) -> None:
        """``no_result`` is rejected outright — it is not surfaced as data."""
        llm = TurnScriptedLLM([LLMResponse(content=FABRICATED, usage=USAGE)])

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="how many sessions in July?"
        )
        outcome = AgentResultValidator().validate_analytics_result(result)

        assert outcome.passed is False

    async def test_answer_after_a_real_query_is_not_reprompted(
        self, sm, connection_id: str
    ) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=812)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert result.status == "success"
        assert "812" in result.answer
        # One tool turn, one answer turn — no nudge in between.
        assert llm.call_count == 2

    async def test_a_question_needing_no_figures_grounds_itself_on_list_reports(
        self, sm, connection_id: str
    ) -> None:
        """The documented decision for a conversational turn.

        There is no "this one needs no data" escape hatch, because the model is
        the party that would decide it applies. A question that genuinely needs
        no figures is still answerable — ``list_reports`` reads the real
        catalogue and the real journal — so the nudge points at it and the
        answer then succeeds. A model that will not read even that gets
        ``no_result``.
        """
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        llm = TurnScriptedLLM(
            [
                LLMResponse(content="Hi! Ask me about your analytics.", usage=USAGE),
                LLMResponse(content="", tool_calls=[_tool_call("list_reports")], usage=USAGE),
                LLMResponse(content="This connection covers the overview report.", usage=USAGE),
            ]
        )

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="what can you tell me about?"
        )

        assert result.status == "success"
        assert "overview" in result.answer
        assert llm.call_count == 3

    async def test_coverage_alone_is_enough_grounding_to_answer(
        self, sm, connection_id: str
    ) -> None:
        """A pure coverage question is answerable from the journal alone."""
        llm = ScriptedLLM([_tool_call("coverage", report="overview")])

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="has anything been collected?"
        )

        assert result.status == "success"
        assert llm.call_count == 2


# ---------------------------------------------------------------------------
# Partial-data caveat
# ---------------------------------------------------------------------------


class TestPartialDataCaveat:
    async def test_failed_period_in_the_window_is_named(self, sm, connection_id: str) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=120)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        await _journal(
            sm, connection_id, "overview", FAILED_DAY, "failed", error="GA4 quota exhausted"
        )

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=FAILED_DAY,
                )
            ]
        )
        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions this window?"
        )

        assert result.status == "success"
        assert "PARTIAL DATA" in result.answer
        assert FAILED_DAY in result.answer
        assert "quota exhausted" in result.answer
        # The 11th is inside the window and was never collected either.
        assert set(result.pending_periods) == {NEVER_COLLECTED_DAY, FAILED_DAY}

    async def test_fully_collected_window_carries_no_partial_caveat(
        self, sm, connection_id: str
    ) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=120)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert "PARTIAL DATA" not in result.answer
        assert result.pending_periods == []

    async def test_freshness_states_the_latest_collected_period(
        self, sm, connection_id: str
    ) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=120)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert "Freshness" in result.answer
        assert COLLECTED_ZERO_DAY in result.answer


# ---------------------------------------------------------------------------
# Pruned journal rows — a gap in the record is not a gap in the data
# ---------------------------------------------------------------------------


class TestPrunedJournalRecord:
    """``journal.prune(older_than_days=400)`` deletes journal rows.

    Nothing prunes the fact tables — deliberately (ADR-0001 §5: expiring them
    would silently turn answered history into "not collected"). So after the
    retention window a queried period can have real rows and no journal row, and
    the two honest facts about it are that the numbers ARE counted and that only
    the record of collecting them is gone. Reading "no journal row" as "never
    collected" produces an answer that prints the numbers and denies them in the
    same breath.
    """

    async def _ask_over_the_pruned_day(self, sm, connection_id: str) -> AnalyticsResult:
        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report", report="overview", date_from=PRUNED_DAY, date_to=PRUNED_DAY
                )
            ]
        )
        return await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question=f"sessions on {PRUNED_DAY}?"
        )

    async def test_rows_without_a_journal_row_are_reported_not_denied(
        self, sm, connection_id: str
    ) -> None:
        # Collected long ago: the rows survived, the journal row did not.
        await _overview_row(sm, connection_id, PRUNED_DAY, sessions=1204)

        result = await self._ask_over_the_pruned_day(sm, connection_id)

        assert result.status == "success"
        assert "1204" in result.answer
        # None of the three ways the old code called this data missing.
        assert "NOT COLLECTED" not in result.answer
        assert "not collected" not in result.answer.lower()
        assert "never been collected" not in result.answer
        assert "excluded from the numbers above" not in result.answer
        # …and it is not a period the validator may warn is absent from the totals.
        assert result.pending_periods == []
        assert AgentResultValidator().validate_analytics_result(result).warnings == []
        # What the user is told instead.
        assert "aged out" in result.answer.lower()

    async def test_a_period_with_neither_rows_nor_a_record_is_still_never_collected(
        self, sm, connection_id: str
    ) -> None:
        """The other half of the distinction: no record AND no rows really is a gap."""
        result = await self._ask_over_the_pruned_day(sm, connection_id)

        assert "NOT COLLECTED" in result.answer
        assert result.pending_periods == [PRUNED_DAY]


# ---------------------------------------------------------------------------
# Tenant isolation — both reads are scoped to the connection
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Two connections, so a dropped ``connection_id ==`` predicate is visible.

    A query touches three connection-scoped reads: the aggregate (the numbers),
    the journal (whether those numbers are all of them) and the row-presence
    probe (whether an unrecorded period was collected or merely pruned). Ours
    holds one day and theirs holds both, so dropping the predicate from any one
    of the three changes an assertion below.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, sm, connection_id: str, other_connection_id: str) -> None:
        # Ours: one collected day, and nothing at all on the second day.
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=111)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        # Theirs: rows and a journal row on both days.
        await _overview_row(
            sm,
            other_connection_id,
            COLLECTED_ZERO_DAY,
            sessions=999,
            property_id=OTHER_PROPERTY_ID,
        )
        await _overview_row(
            sm,
            other_connection_id,
            NEVER_COLLECTED_DAY,
            sessions=888,
            property_id=OTHER_PROPERTY_ID,
        )
        await _journal(
            sm, other_connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1
        )
        await _journal(
            sm, other_connection_id, "overview", NEVER_COLLECTED_DAY, "ok", rows_written=1
        )

    async def _run(self, sm, connection_id: str) -> AnalyticsResult:
        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=NEVER_COLLECTED_DAY,
                    group_by="property_id",
                )
            ]
        )
        return await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions this window?"
        )

    async def test_another_connections_rows_are_never_summed_into_ours(
        self, sm, connection_id: str
    ) -> None:
        result = await self._run(sm, connection_id)

        assert [row[0] for row in result.rows] == [PROPERTY_ID]
        assert result.rows[0][1] == 111
        assert OTHER_PROPERTY_ID not in result.answer

    async def test_another_connections_journal_never_fills_our_gap(
        self, sm, connection_id: str
    ) -> None:
        result = await self._run(sm, connection_id)

        assert result.pending_periods == [NEVER_COLLECTED_DAY]
        assert "NOT COLLECTED" in result.answer
        assert NEVER_COLLECTED_DAY in result.answer

    async def test_another_connections_rows_never_vouch_for_our_coverage(
        self, sm, connection_id: str
    ) -> None:
        """The row-presence probe is scoped too.

        It decides "never collected" versus "collected, record pruned". Reading
        it unscoped would let a neighbouring tenant's rows turn our genuine gap
        into a reassuring "the data is retained" line.
        """
        result = await self._run(sm, connection_id)

        assert "AGED OUT" not in result.answer
        assert "NOT COLLECTED" in result.answer


# ---------------------------------------------------------------------------
# DataGate
# ---------------------------------------------------------------------------


class TestDataGate:
    async def _run_with_negative_sessions(self, sm, connection_id: str) -> AnalyticsResult:
        await _overview_row(sm, connection_id, NEGATIVE_DAY, sessions=-5)
        await _journal(sm, connection_id, "overview", NEGATIVE_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report", report="overview", date_from=NEGATIVE_DAY, date_to=NEGATIVE_DAY
                )
            ]
        )
        return await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

    async def test_negative_session_count_blocks_the_answer(
        self, sm, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)

        result = await self._run_with_negative_sessions(sm, connection_id)

        assert result.status == "error"
        assert result.answer == ""
        assert "sessions" in (result.error or "")
        assert "-5" in (result.error or "")

    async def test_hard_checks_disabled_warns_instead_of_blocking(
        self, sm, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", False)

        result = await self._run_with_negative_sessions(sm, connection_id)

        assert result.status == "success"
        assert result.answer
        assert any("sessions" in caveat for caveat in result.caveats)

    async def test_plausible_data_passes_the_gate(self, sm, connection_id: str) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=812)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert result.status == "success"
        assert "812" in result.answer


# ---------------------------------------------------------------------------
# Loop shape
# ---------------------------------------------------------------------------


class TestLoopShape:
    async def test_iteration_budget_exhausted_yields_no_result(
        self, sm, connection_id: str
    ) -> None:
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=999)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ],
            repeat=True,
        )
        agent = _agent(llm, sm, max_iterations=2)

        result = await agent.run(_context(), connection_id=connection_id, question="sessions?")

        assert result.status == "no_result"
        assert "999" not in result.answer
        assert "maximum iterations" in result.answer.lower()
        assert llm.call_count == 2

    async def test_llm_failure_is_an_error_not_an_answer(self, sm, connection_id: str) -> None:
        llm = MagicMock()
        llm.get_context_window = MagicMock(return_value=100_000)
        llm.complete = AsyncMock(side_effect=RuntimeError("provider down"))

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert result.status == "error"
        assert result.answer == ""
        assert result.error

    async def test_token_usage_accumulates_across_turns(self, sm, connection_id: str) -> None:
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        llm = ScriptedLLM([_tool_call("list_reports")])

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="what can you tell me?"
        )

        assert result.token_usage["total_tokens"] == 2 * USAGE["total_tokens"]

    async def test_list_reports_names_every_report_and_its_coverage(
        self, sm, connection_id: str
    ) -> None:
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)
        llm = ScriptedLLM([_tool_call("list_reports")])

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="what can you tell me?"
        )
        listing = result.tool_calls_made[0]["result_preview"]

        for name in ("overview", "geo", "platform", "trend", "events"):
            assert name in listing
        assert COLLECTED_ZERO_DAY in listing

    async def test_unknown_tool_name_does_not_crash_the_loop(self, sm, connection_id: str) -> None:
        """The loop survives it — and does not treat an error string as a read.

        The model gets "unknown tool" back, which is not data, so the answer it
        then composes is un-grounded and lands on the refusal path rather than
        being returned as a success.
        """
        llm = ScriptedLLM([_tool_call("drop_everything")])

        result = await _agent(llm, sm).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert result.status == "no_result"
        assert "unknown tool" in result.tool_calls_made[0]["result_preview"].lower()

    async def test_unsupported_vendor_is_refused_honestly(self, sm, connection_id: str) -> None:
        llm = ScriptedLLM([_tool_call("list_reports")])

        result = await _agent(llm, sm).run(
            _context(),
            connection_id=connection_id,
            question="installs?",
            source_type="appstore",
        )

        assert result.status == "error"
        assert "appstore" in (result.error or "")
        assert llm.call_count == 0


# ---------------------------------------------------------------------------
# Answer-quality gate
# ---------------------------------------------------------------------------


class TestAnswerQualityGate:
    async def test_non_accept_verdict_is_surfaced_as_a_caveat(
        self, sm, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "answer_validator_enabled", True)
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=7)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        from app.agents.result_validation import ResultDirective

        gate = MagicMock()
        gate.evaluate = AsyncMock(
            return_value=ResultDirective(action="warn", reason="does not mention the date range")
        )

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm, answer_gate=gate).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert "does not mention the date range" in result.answer
        gate.evaluate.assert_awaited_once()

    async def test_gate_failure_does_not_lose_the_answer(
        self, sm, connection_id: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "answer_validator_enabled", True)
        await _overview_row(sm, connection_id, COLLECTED_ZERO_DAY, sessions=7)
        await _journal(sm, connection_id, "overview", COLLECTED_ZERO_DAY, "ok", rows_written=1)

        gate = MagicMock()
        gate.evaluate = AsyncMock(side_effect=RuntimeError("validator exploded"))

        llm = ScriptedLLM(
            [
                _tool_call(
                    "query_report",
                    report="overview",
                    date_from=COLLECTED_ZERO_DAY,
                    date_to=COLLECTED_ZERO_DAY,
                )
            ]
        )
        result = await _agent(llm, sm, answer_gate=gate).run(
            _context(), connection_id=connection_id, question="sessions?"
        )

        assert result.status == "success"
        assert "7" in result.answer


# ---------------------------------------------------------------------------
# validate_analytics_result
# ---------------------------------------------------------------------------


class TestValidateAnalyticsResult:
    def _validate(self, result: AnalyticsResult):
        return AgentResultValidator().validate_analytics_result(result)

    def test_error_fails(self) -> None:
        outcome = self._validate(AnalyticsResult(status="error", error="blocked: negative count"))
        assert outcome.passed is False
        assert "negative count" in outcome.errors[0]

    def test_no_result_fails(self) -> None:
        outcome = self._validate(AnalyticsResult(status="no_result", answer="ran out of steps"))
        assert outcome.passed is False

    def test_empty_answer_warns(self) -> None:
        outcome = self._validate(AnalyticsResult(status="success", answer=""))
        assert outcome.passed is True
        assert any("empty" in w for w in outcome.warnings)

    def test_numbers_over_a_pending_window_warn(self) -> None:
        outcome = self._validate(
            AnalyticsResult(
                status="success",
                answer="You had 1,204 sessions.",
                raw_answer="You had 1,204 sessions.",
                pending_periods=[NEVER_COLLECTED_DAY],
            )
        )
        assert outcome.passed is True
        assert any(NEVER_COLLECTED_DAY in w for w in outcome.warnings)

    def test_no_numbers_over_a_pending_window_does_not_warn(self) -> None:
        """The warning is for *figures* over a gap, not for naming the gap.

        Asserted as "no warnings at all" rather than "no warning containing some
        phrase": the validator emits one warning here or none, so an assertion
        on a phrase it never uses would hold no matter what the guard did.
        """
        outcome = self._validate(
            AnalyticsResult(
                status="success",
                answer="Nothing has been collected for that window yet.",
                raw_answer="Nothing has been collected for that window yet.",
                pending_periods=[NEVER_COLLECTED_DAY],
            )
        )
        assert outcome.warnings == []

    def test_is_stricter_than_the_mcp_validator(self) -> None:
        """The MCP validator has no coverage notion; the analytics one must."""
        validator = AgentResultValidator()
        result = AnalyticsResult(
            status="success",
            answer="You had 1,204 sessions.",
            raw_answer="You had 1,204 sessions.",
            pending_periods=[NEVER_COLLECTED_DAY],
        )
        assert validator.validate_mcp_result(result).warnings == []
        assert validator.validate_analytics_result(result).warnings != []
