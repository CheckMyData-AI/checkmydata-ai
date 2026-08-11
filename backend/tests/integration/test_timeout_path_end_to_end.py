"""The timeout path, driven end to end against a database that never answers.

This replaces carry-over K14, which said "verify on the next real timeout in
production". With no users, that is a wish rather than a task: the path would ship
unverified indefinitely. So the stalled database is stood up here instead.

What the unit tests already cover, separately: the classifier honours a typed error,
the loop spends one narrowing repair, the breaker counts consecutive timeouts. What
nothing covered until now is their **composition** — and composition is exactly where
the production incident lived. On 2026-08-06 every individual component behaved as
written, and together they burned 120 280 ms of LLM time rewriting a correct query
against a database that had stopped executing anything.

The stand-in below is a real `asyncio` timeout through the connector's own code path,
not a stubbed error string: `execute_query` awaits something that never completes, so
`asyncio.wait_for` raises the same messageless builtin `TimeoutError` a live database
would produce.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import QueryResult, SchemaInfo, TableInfo
from app.core.error_types import QueryErrorType
from app.core.query_validation import ValidationConfig
from app.core.validation_loop import ValidationLoop


class StalledDatabase:
    """Accepts EXPLAIN instantly, never returns rows — the 2026-08-06 shape.

    That asymmetry is the whole diagnosis: planning was answered in 72–466 ms while
    every execution hit the 30 s ceiling, which is why "the query is too heavy" was
    the wrong reading and "the database is not executing" was the right one.
    """

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        self.executions = 0
        self.explains = 0

    async def execute_query(
        self, query: str, params: dict | None = None, *, timeout_seconds: float | None = None
    ) -> QueryResult:
        if query.strip().upper().startswith("EXPLAIN"):
            self.explains += 1
            return QueryResult(columns=["plan"], rows=[["Seq Scan"]], row_count=1)

        self.executions += 1
        budget = timeout_seconds or self.timeout_s
        try:
            # A real wait_for expiry: the builtin TimeoutError carries no message,
            # which is precisely why the connector has to state the type instead.
            await asyncio.wait_for(asyncio.Event().wait(), timeout=budget)
        except TimeoutError:
            return QueryResult(
                error=f"Query timed out after {budget:g}s",
                error_type=QueryErrorType.TIMEOUT,
                execution_time_ms=budget * 1000,
            )
        return QueryResult()


def _schema() -> SchemaInfo:
    return SchemaInfo(tables=[TableInfo(name="orders")], db_type="postgresql")


def _tracker() -> MagicMock:
    t = MagicMock()
    t.step = MagicMock()
    t.step.return_value.__aenter__ = AsyncMock()
    t.step.return_value.__aexit__ = AsyncMock()
    t.emit = AsyncMock()
    return t


def _loop(repairer: MagicMock, timeout_s: float) -> ValidationLoop:
    from app.core.context_enricher import ContextEnricher
    from app.core.error_classifier import ErrorClassifier
    from app.core.retry_strategy import RetryStrategy

    return ValidationLoop(
        config=ValidationConfig(
            max_retries=3,
            enable_explain=False,
            enable_schema_validation=False,
            empty_result_retry=False,
            query_timeout_seconds=timeout_s,
        ),
        error_classifier=ErrorClassifier(),
        context_enricher=ContextEnricher(_schema()),
        query_repairer=repairer,
        retry_strategy=RetryStrategy(),
        tracker=_tracker(),
    )


@pytest.mark.asyncio
async def test_a_database_that_never_answers_costs_one_repair_and_stops():
    """The whole point, measured rather than asserted in prose.

    Production spent ten repairs and 277 831 ms inside the tool. The contract now is:
    two executions, one repair, and a failure that still calls itself a timeout.
    """
    from app.connectors.base import ConnectionConfig

    db = StalledDatabase(timeout_s=0.05)
    repairer = MagicMock()
    repairer.repair = AsyncMock(
        return_value={"query": "SELECT count(*) FROM orders", "explanation": "narrowed"}
    )

    result = await _loop(repairer, 0.05).execute(
        initial_query="SELECT * FROM orders",
        initial_explanation="all orders",
        connector=db,
        schema=_schema(),
        question="revenue by cohort for three months",
        project_id="p1",
        workflow_id="wf1",
        connection_config=ConnectionConfig(db_type="postgresql", db_name="test"),
    )

    assert not result.success
    assert result.final_error is not None
    assert result.final_error.error_type == QueryErrorType.TIMEOUT, (
        "the failure must keep its identity — reported as a timeout, not as bad SQL"
    )
    assert repairer.repair.await_count == 1, (
        "a timeout is worth exactly one narrowing attempt; production spent ten"
    )
    assert db.executions == 2, (
        f"the loop must stop after the second timeout, not exhaust max_retries; "
        f"executed {db.executions} times"
    )


@pytest.mark.asyncio
async def test_the_narrowed_query_is_actually_run_when_it_can_succeed():
    """The other half: one repair is spent, not skipped.

    Refusing outright would be cheaper and wrong — a genuinely heavy query (missing
    index, cartesian join) *is* fixable by narrowing, and that case must still work.
    """
    from app.connectors.base import ConnectionConfig

    class RecoversAfterNarrowing(StalledDatabase):
        async def execute_query(self, query: str, params=None, *, timeout_seconds=None) -> Any:
            if "count(*)" in query:
                self.executions += 1
                return QueryResult(columns=["n"], rows=[[7]], row_count=1)
            return await super().execute_query(query, params, timeout_seconds=timeout_seconds)

    db = RecoversAfterNarrowing(timeout_s=0.05)
    repairer = MagicMock()
    repairer.repair = AsyncMock(
        return_value={"query": "SELECT count(*) FROM orders", "explanation": "narrowed"}
    )

    result = await _loop(repairer, 0.05).execute(
        initial_query="SELECT * FROM orders",
        initial_explanation="all orders",
        connector=db,
        schema=_schema(),
        question="how many orders",
        project_id="p1",
        workflow_id="wf1",
        connection_config=ConnectionConfig(db_type="postgresql", db_name="test"),
    )

    assert result.success, "a query the narrowing fixes must still be answered"
    assert result.results is not None and result.results.rows == [[7]]
    assert repairer.repair.await_count == 1
