"""Tests for the diagnostics QueryFailure persistence layer.

Covers ``QueryFailureService.record`` and the best-effort module helper
``maybe_record_query_failure``: the row is built from the repair-attempt
history (``QueryAttempt``/``QueryError`` from ``app.core.query_validation``),
truncation caps are honoured, the recorder no-ops when the flag is off or no
attempt errored, and a DB failure inside ``record`` never raises into the
caller while still bumping the self-observability counter.

Everything runs against an in-memory async SQLite engine — no network, no
real model calls.
"""

from __future__ import annotations

import json
import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.query_validation import QueryAttempt, QueryError, QueryErrorType
from app.models.base import Base
from app.models.project import Project
from app.models.query_failure import QueryFailure
from app.services import query_failure_service as qfs_module
from app.services.query_failure_service import (
    QueryFailureService,
    maybe_record_query_failure,
)


@pytest_asyncio.fixture
async def engine_and_sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, sm
    await engine.dispose()


async def _seed_project(sm) -> str:
    """Create a Project row (FK target for QueryFailure) and return its id."""
    project_id = str(uuid.uuid4())
    async with sm() as session:
        session.add(Project(id=project_id, name="diag-test"))
        await session.commit()
    return project_id


def _attempt(
    n: int,
    query: str,
    *,
    error_type: QueryErrorType | None = None,
    raw_error: str = "",
    elapsed_ms: float = 1.0,
) -> QueryAttempt:
    err = (
        QueryError(error_type=error_type, message=raw_error or "boom", raw_error=raw_error)
        if error_type is not None
        else None
    )
    return QueryAttempt(
        attempt_number=n,
        query=query,
        explanation="",
        error=err,
        elapsed_ms=elapsed_ms,
    )


def _context(project_id: str, *, connection_id: str | None = "conn-1"):
    """Minimal stand-in for AgentContext used by maybe_record_query_failure."""
    from types import SimpleNamespace

    connection_config = SimpleNamespace(db_type="postgres", connection_id=connection_id)
    return SimpleNamespace(
        project_id=project_id,
        connection_config=connection_config,
        workflow_id="wf-1",
        user_question="how many users?",
        extra={"session_id": "sess-1", "message_id": "msg-1"},
    )


class TestRecord:
    async def test_records_failed_query_row(self, engine_and_sm):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        attempts = [
            _attempt(1, "SELECT bad FROM users", error_type=QueryErrorType.SYNTAX_ERROR),
            _attempt(
                2,
                "SELECT broken FROM users",
                error_type=QueryErrorType.COLUMN_NOT_FOUND,
                raw_error="column broken does not exist",
            ),
        ]

        async with sm() as session:
            await QueryFailureService().record(
                session,
                project_id=project_id,
                connection_id="conn-1",
                workflow_id="wf-1",
                trace_id="trace-1",
                session_id="sess-1",
                message_id="msg-1",
                db_type="postgres",
                question="how many users?",
                attempts=attempts,
                final_status="failed",
            )

        async with sm() as session:
            rows = (await session.execute(select(QueryFailure))).scalars().all()

        assert len(rows) == 1
        row = rows[0]
        assert row.project_id == project_id
        assert row.failed_sql == "SELECT broken FROM users"
        assert row.error_type == "column_not_found"
        assert row.raw_error == "column broken does not exist"
        assert row.final_status == "failed"
        assert row.attempt_count == 2
        assert row.db_type == "postgres"
        assert row.question == "how many users?"
        attempts_json = json.loads(row.attempts_json)
        assert [a["attempt"] for a in attempts_json] == [1, 2]
        assert attempts_json[1]["error_type"] == "column_not_found"

    async def test_no_errored_attempt_falls_back_to_unknown(self, engine_and_sm):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        attempts = [_attempt(1, "SELECT 1")]  # no error on any attempt

        async with sm() as session:
            await QueryFailureService().record(
                session,
                project_id=project_id,
                connection_id=None,
                workflow_id=None,
                trace_id=None,
                session_id=None,
                message_id=None,
                db_type="postgres",
                question="q",
                attempts=attempts,
                final_status="failed",
            )

        async with sm() as session:
            row = (await session.execute(select(QueryFailure))).scalars().one()
        assert row.failed_sql == "SELECT 1"
        assert row.error_type == "unknown"

    async def test_truncates_attempts_and_raw_error(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)

        monkeypatch.setattr(settings, "diagnostics_attempt_history_max", 3, raising=False)
        monkeypatch.setattr(settings, "diagnostics_raw_error_max_chars", 50, raising=False)

        long_err = "x" * 500
        attempts = [
            _attempt(
                i,
                f"SELECT {i}",
                error_type=QueryErrorType.SYNTAX_ERROR,
                raw_error=long_err,
            )
            for i in range(1, 11)  # 10 attempts, all errored
        ]

        async with sm() as session:
            await QueryFailureService().record(
                session,
                project_id=project_id,
                connection_id="conn-1",
                workflow_id="wf-1",
                trace_id=None,
                session_id=None,
                message_id=None,
                db_type="postgres",
                question="q",
                attempts=attempts,
                final_status="failed",
            )

        async with sm() as session:
            row = (await session.execute(select(QueryFailure))).scalars().one()

        # attempt_count reflects the FULL count, not the truncated serialization.
        assert row.attempt_count == 10
        serialized = json.loads(row.attempts_json)
        assert len(serialized) == 3
        # Top-level raw_error honours the configurable per-row cap (50 here).
        assert len(row.raw_error) <= 50
        # Per-attempt history fields are capped to the fixed ~2000-char field cap
        # (independent of the row-level cap) so a long error is preserved here.
        for a in serialized:
            assert len(a["raw_error"]) <= qfs_module._PER_ATTEMPT_FIELD_CAP
            assert len(a["raw_error"]) == 500  # 500 < 2000, so retained in full


class TestMaybeRecordQueryFailure:
    async def test_records_failed_via_helper(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        monkeypatch.setattr(settings, "diagnostics_capture_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        attempts = [
            _attempt(
                1,
                "SELECT bad FROM t",
                error_type=QueryErrorType.COLUMN_NOT_FOUND,
                raw_error="no such column",
            )
        ]
        await maybe_record_query_failure(
            context=_context(project_id),
            attempts=attempts,
            loop_success=False,
            trace_id="trace-9",
        )

        async with sm() as session:
            row = (await session.execute(select(QueryFailure))).scalars().one()
        assert row.final_status == "failed"
        assert row.failed_sql == "SELECT bad FROM t"
        assert row.error_type == "column_not_found"
        assert row.connection_id == "conn-1"
        assert row.session_id == "sess-1"
        assert row.message_id == "msg-1"
        assert row.trace_id == "trace-9"

    async def test_recovered_status_when_loop_success(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        monkeypatch.setattr(settings, "diagnostics_capture_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        attempts = [
            _attempt(1, "SELECT bad", error_type=QueryErrorType.SYNTAX_ERROR),
            _attempt(2, "SELECT good"),  # recovered: final attempt has no error
        ]
        await maybe_record_query_failure(
            context=_context(project_id),
            attempts=attempts,
            loop_success=True,
        )

        async with sm() as session:
            row = (await session.execute(select(QueryFailure))).scalars().one()
        assert row.final_status == "recovered"

    async def test_noop_when_flag_disabled(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        monkeypatch.setattr(settings, "diagnostics_capture_enabled", False, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        attempts = [_attempt(1, "SELECT bad", error_type=QueryErrorType.SYNTAX_ERROR)]
        await maybe_record_query_failure(
            context=_context(project_id),
            attempts=attempts,
            loop_success=False,
        )

        async with sm() as session:
            rows = (await session.execute(select(QueryFailure))).scalars().all()
        assert rows == []

    async def test_noop_when_no_errored_attempt(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        monkeypatch.setattr(settings, "diagnostics_capture_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        attempts = [_attempt(1, "SELECT 1"), _attempt(2, "SELECT 2")]  # none errored
        await maybe_record_query_failure(
            context=_context(project_id),
            attempts=attempts,
            loop_success=True,
        )

        async with sm() as session:
            rows = (await session.execute(select(QueryFailure))).scalars().all()
        assert rows == []

    async def test_db_error_does_not_raise_and_bumps_counter(self, engine_and_sm, monkeypatch):
        _engine, sm = engine_and_sm
        project_id = await _seed_project(sm)
        monkeypatch.setattr(settings, "diagnostics_capture_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        bumped = {"count": 0}

        def _fake_record_failure() -> None:
            bumped["count"] += 1

        monkeypatch.setattr(qfs_module, "record_diagnostics_persist_failure", _fake_record_failure)

        async def _boom(self, *args, **kwargs):  # noqa: ANN001
            raise RuntimeError("commit blew up")

        monkeypatch.setattr(QueryFailureService, "record", _boom)

        attempts = [_attempt(1, "SELECT bad", error_type=QueryErrorType.SYNTAX_ERROR)]
        # Must NOT raise.
        await maybe_record_query_failure(
            context=_context(project_id),
            attempts=attempts,
            loop_success=False,
        )

        assert bumped["count"] == 1
        async with sm() as session:
            rows = (await session.execute(select(QueryFailure))).scalars().all()
        assert rows == []
