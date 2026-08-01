"""T11 — the analytics spine end to end: vendor → tables → journal → answer.

Every other analytics test proves one seam. This one crosses all of them in a
single run, because the bugs that survive a green unit suite live *between* the
pieces: a credential that encrypts fine and decrypts into the wrong dict key, a
report whose columns are correct in isolation but land one column left in the
fact table, a journal verdict that is written but never read back by the agent.

The route taken here is the production one, with exactly one substitution: the
GA4 **client** is a fake, injected into a real :class:`GA4Adapter`. Everything
downstream of ``run_report`` is the shipped code — the adapter's parsing and
quota handling, the collect service's period arithmetic and upsert, the journal,
the ORM models, the agent's parameterised reads and its honesty gates. Nothing
here touches the network or needs a credential, and the credential that *is*
created goes through the real API, is really Fernet-encrypted, and is really
decrypted again by the collect service (asserted, not assumed).

Five things are proven, one per test:

1. **The happy path across every seam.** The number the fake vendor returned is
   the number in the agent's sentence.
2. **A rerun changes nothing.** Same fake data twice ⇒ identical row counts and
   still one journal row per ``(report, period)``. The second run is asserted to
   have actually called the vendor, so "idempotent" cannot pass by doing nothing.
3. **A mid-run failure is `partial`, and the answer says so.** One period of one
   report hits an exhausted vendor quota. The outcome says ``partial``, the other
   periods still wrote, the journal records the failure — and, the part that
   matters to a user, the agent's answer over that window carries the caveat.
   Asserted on the answer text: an honest outcome object nobody surfaces is not
   honesty.
4. **Empty is not zero.** A day the vendor reported as 0 sessions answers "0"; a
   day that was never collected must answer "not collected" and must not claim a
   zero. The two answers must differ — an implementation that reads "no rows" as
   "zero" makes them identical, which is a fabricated measurement (vision §7).
5. **Delete really cascades.** Deleting the connection removes every journal row
   and every fact row for it — counted before (>0) and after (0), so the test
   cannot pass against a connection that never had data.

Dates are pinned in the past (July 2026) rather than derived from ``today``: the
collect window is injected, and a fixed window keeps DataGate's future-date check
out of the way permanently rather than until the next clock tick.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from google.analytics.data_v1beta.types import (
    DimensionHeader,
    DimensionValue,
    MetricHeader,
    MetricValue,
    PropertyQuota,
    QuotaStatus,
    Row,
    RunReportRequest,
    RunReportResponse,
)
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.analytics_agent import AnalyticsAgent, AnalyticsResult
from app.agents.base import AgentContext
from app.analytics.ga4.adapter import GA4Adapter
from app.analytics.ga4.config import CREDENTIAL_SECRET_KEY
from app.analytics.ga4.reports import GA4_REPORTS, GA4Field, GA4ReportSpec
from app.analytics.outcome import CollectOutcome
from app.config import settings
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall
from app.models.analytics_ga4 import GA4_FACT_MODELS, GA4OverviewDaily
from app.models.analytics_import import AnalyticsImport
from app.models.connection import Connection
from app.services.analytics_collect_service import AnalyticsCollectService

# ---------------------------------------------------------------------------
# The world under test
# ---------------------------------------------------------------------------

PROPERTY_ID = "294380179"

#: Injected "today". The collect window always ends yesterday, so with
#: ``backfill_days = 3`` the expected periods are 2026-07-13 … 2026-07-15.
TODAY = dt.date(2026, 7, 16)
BACKFILL_DAYS = 3
COLLECTED_DAYS = ["2026-07-13", "2026-07-14", "2026-07-15"]

#: One day *below* the collect window: never fetched, no journal row, no fact
#: row. The only honest answer about it is "not collected".
NEVER_COLLECTED_DAY = "2026-07-12"

#: Distinctive per-day session counts so the number in the final answer can only
#: have come from the fake vendor's payload.
SESSIONS_BY_DAY: dict[str, int] = {
    "2026-07-13": 111,
    "2026-07-14": 222,
    "2026-07-15": 333,
}
TOTAL_SESSIONS = 666

#: Requests per collect run: five reports × three periods × one property.
FULL_RUN_REQUESTS = len(GA4_REPORTS) * len(COLLECTED_DAYS)

GA4_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIBT9E2ESECRET\n-----END PRIVATE KEY-----\n"
GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "e2e-project",
        "client_email": "collector@e2e-project.iam.gserviceaccount.com",
        "private_key": GA4_PRIVATE_KEY,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

SOURCE_CONFIG: dict[str, Any] = {
    "property_ids": [PROPERTY_ID],
    "backfill_days": BACKFILL_DAYS,
    "event_names": ["pin_show_promo"],
}

#: Readable dimension values, so a swapped column is visible in an assertion
#: rather than hiding behind ``dimension-value``.
_DIMENSION_VALUES: dict[str, str] = {
    "country": "Germany",
    "platform": "web",
    "deviceCategory": "mobile",
    "sessionDefaultChannelGroup": "Organic Search",
    "eventName": "pin_show_promo",
}


# ---------------------------------------------------------------------------
# The fake vendor
# ---------------------------------------------------------------------------


def _spec_for(request: RunReportRequest) -> GA4ReportSpec:
    """Which report a request is for, matched on its dimensions.

    Derived from the shipped specs rather than hard-coded, so a renamed
    dimension fails here loudly instead of quietly serving the wrong report.
    """
    dimensions = tuple(dimension.name for dimension in request.dimensions)
    for spec in GA4_REPORTS:
        if tuple(spec.dimension_names) == dimensions:
            return spec
    raise AssertionError(f"no GA4 report declares dimensions {dimensions}")


def _metric_value(api_name: str, sessions: int) -> str:
    """One metric, as GA4 sends it: a **string**, always."""
    if api_name in ("sessions", "activeUsers"):
        return str(sessions)
    if api_name == "newUsers":
        return str(sessions // 2)
    if api_name == "screenPageViews":
        return str(sessions * 2)
    if api_name in ("eventCount", "keyEvents"):
        return str(sessions * 3)
    if api_name == "totalRevenue":
        return f"{sessions}.5000"
    raise AssertionError(f"the fake vendor has no value for metric {api_name!r}")


def _dimension_value(field: GA4Field, day: str) -> str:
    if field.kind == "date":
        return day.replace("-", "")
    return _DIMENSION_VALUES.get(field.api_name, f"{field.api_name}-value")


class FakeGA4Client:
    """A GA4 property with scripted daily traffic. Records every request.

    Args:
        sessions_by_day: Sessions the property reports per day. A day present
            with value ``0`` is a *collected zero* — the whole point of Δ2's
            ``keep_empty_rows`` — and is served as a real row, not as no rows.
        quota_exhausted: ``(report, period)`` pairs answered with a response
            whose quota block is spent, which is how a real mid-run quota wall
            arrives. The adapter turns that into ``QuotaExhaustedError``.
    """

    def __init__(
        self,
        *,
        sessions_by_day: dict[str, int] | None = None,
        quota_exhausted: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self.sessions_by_day = dict(sessions_by_day or SESSIONS_BY_DAY)
        self.quota_exhausted = quota_exhausted
        self.requests: list[RunReportRequest] = []

    async def run_report(self, request: RunReportRequest) -> RunReportResponse:
        self.requests.append(request)
        spec = _spec_for(request)
        day = request.date_ranges[0].start_date

        if (spec.name, day) in self.quota_exhausted:
            return RunReportResponse(
                dimension_headers=[DimensionHeader(name=n) for n in spec.dimension_names],
                metric_headers=[MetricHeader(name=n) for n in spec.metric_names],
                rows=[],
                row_count=0,
                property_quota=PropertyQuota(
                    tokens_per_hour=QuotaStatus(consumed=40_000, remaining=0)
                ),
            )

        if int(request.offset or 0) > 0:
            # One page holds everything this fake has; a second page is empty.
            return RunReportResponse(
                dimension_headers=[DimensionHeader(name=n) for n in spec.dimension_names],
                metric_headers=[MetricHeader(name=n) for n in spec.metric_names],
                rows=[],
                row_count=1,
            )

        sessions = self.sessions_by_day.get(day, 10)
        row = Row(
            dimension_values=[
                DimensionValue(value=_dimension_value(field, day)) for field in spec.dimensions
            ],
            metric_values=[
                MetricValue(value=_metric_value(field.api_name, sessions)) for field in spec.metrics
            ],
        )
        return RunReportResponse(
            dimension_headers=[DimensionHeader(name=n) for n in spec.dimension_names],
            metric_headers=[MetricHeader(name=n) for n in spec.metric_names],
            rows=[row],
            row_count=1,
        )


class RecordingGA4Adapter(GA4Adapter):
    """A real adapter that remembers the config it was connected with.

    Used to prove the credential seam: the secret the API encrypted has to come
    back out of the collect service decrypted and under the key the adapter
    reads. Asserting on the plaintext is the only way to catch a mismatch that
    an injected client would otherwise hide.
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client=client)
        self.configs: list[Any] = []

    async def connect(self, config: Any) -> None:
        self.configs.append(config)
        await super().connect(config)


class Vendor:
    """The fake client plus every adapter the collect service built from it."""

    def __init__(self, **client_kwargs: Any) -> None:
        self.client = FakeGA4Client(**client_kwargs)
        self.adapters: list[RecordingGA4Adapter] = []

    def factory(self, _connection: Connection) -> RecordingGA4Adapter:
        adapter = RecordingGA4Adapter(self.client)
        self.adapters.append(adapter)
        return adapter

    @property
    def requests(self) -> list[RunReportRequest]:
        return self.client.requests


# ---------------------------------------------------------------------------
# The scripted LLM
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Fake ``LLMRouter``: issues scripted tool calls, then echoes the results.

    Echoing rather than inventing prose keeps every assertion in this module
    about what the agent's own tools and gates produced. A model that invented
    text would let a caveat-free answer pass because the fake happened to
    mention the right words.
    """

    def __init__(self, tool_calls: list[ToolCall]) -> None:
        self._tool_calls = tool_calls
        self.call_count = 0

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
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if self.call_count == 1:
            return LLMResponse(content="", tool_calls=list(self._tool_calls), usage=usage)
        echoed = "\n".join(message.content for message in messages if message.role == "tool")
        return LLMResponse(content=f"From the collected data:\n{echoed}", usage=usage)


def _tool_call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"tc-{name}", name=name, arguments=dict(arguments))


def _context(question: str) -> AgentContext:
    tracker = MagicMock(spec=WorkflowTracker)
    tracker.emit = AsyncMock()
    return AgentContext(
        project_id="proj-e2e",
        connection_config=None,
        user_question=question,
        chat_history=[],
        llm_router=MagicMock(),
        tracker=tracker,
        workflow_id="wf-e2e",
    )


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_answer_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer-quality gate calls an LLM; it has its own unit test."""
    monkeypatch.setattr(settings, "answer_validator_enabled", False)


@pytest_asyncio.fixture()
async def ga4_connection(auth_client: AsyncClient, db_session: AsyncSession):
    """A committed GA4 connection created through the real API. Yields its id.

    Going through the API (rather than inserting a row) is deliberate: the
    credential is encrypted by the service the product uses, and the connection
    is shaped by the validator the product uses, so the collect run below is
    reading what a real user's setup would have written.
    """
    project = await auth_client.post("/api/projects", json={"name": f"E2E {uuid.uuid4().hex[:6]}"})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]

    credential = await auth_client.post(
        "/api/vendor-credentials",
        json={"name": "ga4-e2e", "provider": "ga4", "secret": GA4_SECRET},
    )
    assert credential.status_code == 200, credential.text
    credential_id = credential.json()["id"]
    assert "PRIVATE KEY" not in credential.text, "the credential response leaked the secret"

    created = await auth_client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "Marketing GA4",
            "source_type": "ga4",
            "vendor_credential_id": credential_id,
            "source_config": SOURCE_CONFIG,
            "collection_enabled": True,
            "collection_hour": 4,
        },
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]

    # Precondition: the row is really committed and really analytics-shaped.
    row = await db_session.get(Connection, connection_id)
    assert row is not None, "the connection was not committed"
    assert row.source_type == "ga4"
    assert row.vendor_credential_id == credential_id
    yield connection_id


async def _collect(session: AsyncSession, connection_id: str, vendor: Vendor) -> CollectOutcome:
    """Run one collection with the fake vendor and the pinned window."""
    service = AnalyticsCollectService(
        adapter_factory=vendor.factory,
        today=lambda: TODAY,
    )
    return await service.collect_in_session(session, connection_id)


async def _count(session: AsyncSession, model: Any, connection_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(model).where(model.connection_id == connection_id)
    )
    return int(result.scalar_one())


async def _journal_rows(
    session: AsyncSession, connection_id: str, report: str | None = None
) -> list[AnalyticsImport]:
    stmt = select(AnalyticsImport).where(AnalyticsImport.connection_id == connection_id)
    if report is not None:
        stmt = stmt.where(AnalyticsImport.report == report)
    return list((await session.execute(stmt.order_by(AnalyticsImport.period))).scalars().all())


async def _ask(
    engine: Any,
    connection_id: str,
    question: str,
    tool_calls: list[ToolCall],
) -> AnalyticsResult:
    """Ask the agent a question, reading the same database the collector wrote."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    agent = AnalyticsAgent(llm_router=ScriptedLLM(tool_calls), session_factory=factory)
    return await agent.run(
        _context(question),
        connection_id=connection_id,
        question=question,
        source_name="Marketing GA4",
        source_type="ga4",
    )


def _overview_window_call(date_from: str, date_to: str, group_by: str = "property_id") -> ToolCall:
    return _tool_call(
        "query_report",
        report="overview",
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
    )


# ---------------------------------------------------------------------------
# 1 — the happy path, across every seam
# ---------------------------------------------------------------------------


async def test_collected_vendor_rows_become_the_number_in_the_answer(
    db_session: AsyncSession, engine: Any, ga4_connection: str
) -> None:
    """Credential → connection → collect → fact tables → journal → answer."""
    connection_id = ga4_connection
    vendor = Vendor()

    # Precondition: nothing on file, so every assertion below is about this run.
    assert await _count(db_session, GA4OverviewDaily, connection_id) == 0
    assert await _journal_rows(db_session, connection_id) == []

    outcome = await _collect(db_session, connection_id, vendor)

    assert outcome.status == "ok", outcome.errors
    assert outcome.errors == []
    assert outcome.periods_ok == FULL_RUN_REQUESTS
    assert outcome.rows_written == FULL_RUN_REQUESTS  # one row per report/period
    assert len(vendor.requests) == FULL_RUN_REQUESTS

    # The credential really made the trip: encrypted by the API, decrypted by
    # the collect service, handed to the adapter under the key it reads.
    assert vendor.adapters, "the collect service never built an adapter"
    config = vendor.adapters[0].configs[0]
    assert config.extra[CREDENTIAL_SECRET_KEY] == GA4_SECRET
    assert config.db_host == "" and config.db_port == 0  # no fabricated database

    # Rows landed in the right table with the right values, in the right columns.
    overview = (
        (
            await db_session.execute(
                select(GA4OverviewDaily)
                .where(GA4OverviewDaily.connection_id == connection_id)
                .order_by(GA4OverviewDaily.date)
            )
        )
        .scalars()
        .all()
    )
    assert [row.date.isoformat() for row in overview] == COLLECTED_DAYS
    assert [row.sessions for row in overview] == [SESSIONS_BY_DAY[d] for d in COLLECTED_DAYS]
    assert [row.property_id for row in overview] == [PROPERTY_ID] * len(COLLECTED_DAYS)
    # screen_page_views is 2× sessions in the fake: a column shifted left or
    # right would put the wrong multiple here.
    assert [row.screen_page_views for row in overview] == [
        SESSIONS_BY_DAY[d] * 2 for d in COLLECTED_DAYS
    ]

    # All five fact tables were written, not just the headline one.
    for model in GA4_FACT_MODELS:
        assert await _count(db_session, model, connection_id) == len(COLLECTED_DAYS), (
            f"{model.__tablename__} is empty"
        )

    # The journal says every period of every report is ok.
    journal_rows = await _journal_rows(db_session, connection_id)
    assert len(journal_rows) == FULL_RUN_REQUESTS
    assert {row.status for row in journal_rows} == {"ok"}
    assert {row.report for row in journal_rows} == {spec.name for spec in GA4_REPORTS}
    assert {row.period for row in journal_rows} == set(COLLECTED_DAYS)

    await db_session.commit()

    result = await _ask(
        engine,
        connection_id,
        "How many sessions did we have between 13 and 15 July 2026?",
        [_overview_window_call(COLLECTED_DAYS[0], COLLECTED_DAYS[-1])],
    )

    assert result.status == "success", result.error
    # The number the vendor returned is the number the user is told.
    assert str(TOTAL_SESSIONS) in result.answer
    assert result.pending_periods == []
    assert "NOT COLLECTED" not in result.answer
    assert "real measurements" in result.answer
    assert result.report == "overview"
    assert result.rows == [
        [
            PROPERTY_ID,
            TOTAL_SESSIONS,
            TOTAL_SESSIONS,
            sum(v // 2 for v in SESSIONS_BY_DAY.values()),
            TOTAL_SESSIONS * 2,
            TOTAL_SESSIONS * 3,
            pytest.approx(sum(v + 0.5 for v in SESSIONS_BY_DAY.values())),
        ]
    ]


# ---------------------------------------------------------------------------
# 2 — rerunning changes nothing
# ---------------------------------------------------------------------------


async def test_rerunning_the_same_collection_writes_no_duplicates(
    db_session: AsyncSession, ga4_connection: str
) -> None:
    """Same vendor data twice ⇒ same rows, same journal, no second copy."""
    connection_id = ga4_connection
    vendor = Vendor()

    first = await _collect(db_session, connection_id, vendor)
    assert first.status == "ok", first.errors
    counts_before = {
        model.__tablename__: await _count(db_session, model, connection_id)
        for model in GA4_FACT_MODELS
    }
    journal_before = await _journal_rows(db_session, connection_id)
    assert all(count > 0 for count in counts_before.values())
    requests_after_first = len(vendor.requests)

    second = await _collect(db_session, connection_id, vendor)

    # The rerun must actually have collected something — an idempotency test
    # that passes because the second run did nothing proves nothing.
    assert len(vendor.requests) > requests_after_first, "the rerun never called the vendor"
    assert second.status == "ok", second.errors
    assert second.rows_written > 0

    counts_after = {
        model.__tablename__: await _count(db_session, model, connection_id)
        for model in GA4_FACT_MODELS
    }
    assert counts_after == counts_before

    journal_after = await _journal_rows(db_session, connection_id)
    assert len(journal_after) == len(journal_before)
    keys = [(row.report, row.period) for row in journal_after]
    assert len(set(keys)) == len(keys), "the journal grew a second row for a period"
    assert {row.status for row in journal_after} == {"ok"}

    # And the values are still the vendor's, not doubled by a second insert.
    overview = (
        (
            await db_session.execute(
                select(GA4OverviewDaily)
                .where(GA4OverviewDaily.connection_id == connection_id)
                .order_by(GA4OverviewDaily.date)
            )
        )
        .scalars()
        .all()
    )
    assert [row.sessions for row in overview] == [SESSIONS_BY_DAY[d] for d in COLLECTED_DAYS]


# ---------------------------------------------------------------------------
# 3 — a mid-run failure is `partial`, and the answer says so
# ---------------------------------------------------------------------------


async def test_a_failed_period_yields_partial_and_the_answer_carries_the_caveat(
    db_session: AsyncSession, engine: Any, ga4_connection: str
) -> None:
    """One period hits the vendor's quota wall; the user is told."""
    connection_id = ga4_connection
    failed_day = COLLECTED_DAYS[1]
    vendor = Vendor(quota_exhausted=frozenset({("overview", failed_day)}))

    outcome = await _collect(db_session, connection_id, vendor)

    assert outcome.status == "partial", outcome.errors
    assert outcome.rows_written > 0
    assert len(outcome.errors) == 1
    assert failed_day in outcome.errors[0]
    assert "quota" in outcome.errors[0].lower()

    # The other periods of the same report still wrote…
    stored_days = sorted(
        row.date.isoformat()
        for row in (
            await db_session.execute(
                select(GA4OverviewDaily).where(GA4OverviewDaily.connection_id == connection_id)
            )
        )
        .scalars()
        .all()
    )
    assert stored_days == [COLLECTED_DAYS[0], COLLECTED_DAYS[2]]
    # …and every other report is untouched by one report's bad day.
    for spec in GA4_REPORTS:
        rows = await _journal_rows(db_session, connection_id, spec.name)
        statuses = {row.period: row.status for row in rows}
        if spec.name == "overview":
            assert statuses == {
                COLLECTED_DAYS[0]: "ok",
                failed_day: "failed",
                COLLECTED_DAYS[2]: "ok",
            }
        else:
            assert statuses == dict.fromkeys(COLLECTED_DAYS, "ok"), spec.name

    failure = next(
        row
        for row in await _journal_rows(db_session, connection_id, "overview")
        if row.period == failed_day
    )
    assert failure.status == "failed"
    assert failure.error and "quota" in failure.error.lower()

    await db_session.commit()

    result = await _ask(
        engine,
        connection_id,
        "How many sessions did we have between 13 and 15 July 2026?",
        [_overview_window_call(COLLECTED_DAYS[0], COLLECTED_DAYS[-1])],
    )

    assert result.status == "success", result.error
    # The honesty requirement: the user is told, in the answer text.
    assert "PARTIAL DATA" in result.answer, result.answer
    assert failed_day in result.answer
    assert "collection failed" in result.answer.lower()
    assert "quota" in result.answer.lower()
    assert "NOT zero" in result.answer
    assert result.pending_periods == [failed_day]
    # The totals really are the surviving days only, and the answer quotes them.
    surviving = SESSIONS_BY_DAY[COLLECTED_DAYS[0]] + SESSIONS_BY_DAY[COLLECTED_DAYS[2]]
    assert str(surviving) in result.answer
    assert result.rows[0][1] == surviving


# ---------------------------------------------------------------------------
# 4 — empty is not zero
# ---------------------------------------------------------------------------


async def test_a_collected_zero_and_a_never_collected_day_answer_differently(
    db_session: AsyncSession, engine: Any, ga4_connection: str
) -> None:
    """0 sessions is a measurement; never collected is an absence of one."""
    connection_id = ga4_connection
    zero_day = COLLECTED_DAYS[0]
    vendor = Vendor(sessions_by_day={**SESSIONS_BY_DAY, zero_day: 0})

    outcome = await _collect(db_session, connection_id, vendor)
    assert outcome.status == "ok", outcome.errors

    # Preconditions that make the two questions genuinely different:
    # the zero day is on file as a real row whose value is 0…
    zero_row = (
        await db_session.execute(
            select(GA4OverviewDaily).where(
                GA4OverviewDaily.connection_id == connection_id,
                GA4OverviewDaily.date == dt.date.fromisoformat(zero_day),
            )
        )
    ).scalar_one()
    assert zero_row.sessions == 0
    zero_journal = next(
        row
        for row in await _journal_rows(db_session, connection_id, "overview")
        if row.period == zero_day
    )
    assert zero_journal.status == "ok"
    # …and the other day has no row and no journal entry at all.
    assert NEVER_COLLECTED_DAY not in {
        row.period for row in await _journal_rows(db_session, connection_id, "overview")
    }
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(GA4OverviewDaily)
            .where(
                GA4OverviewDaily.connection_id == connection_id,
                GA4OverviewDaily.date == dt.date.fromisoformat(NEVER_COLLECTED_DAY),
            )
        )
    ).scalar_one() == 0

    await db_session.commit()

    collected_zero = await _ask(
        engine,
        connection_id,
        f"How many sessions did we have on {zero_day}?",
        [_overview_window_call(zero_day, zero_day)],
    )
    never_collected = await _ask(
        engine,
        connection_id,
        f"How many sessions did we have on {NEVER_COLLECTED_DAY}?",
        [_overview_window_call(NEVER_COLLECTED_DAY, NEVER_COLLECTED_DAY)],
    )

    assert collected_zero.status == "success", collected_zero.error
    assert never_collected.status == "success", never_collected.error

    # The zero day: a real measurement of 0.
    assert collected_zero.rows == [[PROPERTY_ID, 0, 0, 0, 0, 0, pytest.approx(0.5)]]
    assert "real measurements" in collected_zero.answer
    assert "NOT COLLECTED" not in collected_zero.answer
    assert collected_zero.pending_periods == []

    # The never-collected day: no measurement, and it must not read as zero.
    assert never_collected.rows == []
    assert "NOT COLLECTED" in never_collected.answer
    assert NEVER_COLLECTED_DAY in never_collected.answer
    assert "has not been collected yet" in never_collected.answer
    assert "NOT zero" in never_collected.answer
    assert never_collected.pending_periods == [NEVER_COLLECTED_DAY]

    # The load-bearing assertion: the two answers are not the same sentence.
    assert collected_zero.answer != never_collected.answer


# ---------------------------------------------------------------------------
# 5 — deleting the connection erases its cache
# ---------------------------------------------------------------------------


async def test_deleting_the_connection_removes_every_journal_and_fact_row(
    auth_client: AsyncClient, db_session: AsyncSession, ga4_connection: str
) -> None:
    """The whole local cache is scoped to the connection and dies with it."""
    connection_id = ga4_connection
    vendor = Vendor()

    outcome = await _collect(db_session, connection_id, vendor)
    assert outcome.status == "ok", outcome.errors

    before = {
        model.__tablename__: await _count(db_session, model, connection_id)
        for model in GA4_FACT_MODELS
    }
    before["analytics_imports"] = await _count(db_session, AnalyticsImport, connection_id)
    assert all(count > 0 for count in before.values()), before

    await db_session.commit()

    deleted = await auth_client.delete(f"/api/connections/{connection_id}")
    assert deleted.status_code == 200, deleted.text

    assert await db_session.get(Connection, connection_id) is None
    after = {
        model.__tablename__: await _count(db_session, model, connection_id)
        for model in GA4_FACT_MODELS
    }
    after["analytics_imports"] = await _count(db_session, AnalyticsImport, connection_id)
    assert after == dict.fromkeys(before, 0), after
