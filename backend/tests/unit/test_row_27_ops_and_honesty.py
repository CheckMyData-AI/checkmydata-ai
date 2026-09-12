"""Board row 27 — five places the system says something it has not checked.

- **OPS-11** — two writers own `next_run_at` and neither knows about the other.
  `claim_due` advances it atomically at claim time, which is what makes the loop
  multi-dyno safe; `record_run` then overwrites it from `datetime.now()` at
  *completion* time, discarding the slot the claim reserved.
- **OPS-14** — `_deliver_local` runs every persistence hook, including on the Redis
  rebroadcast path. `RunCoordinator._on_event` guards against that explicitly;
  `TracePersistenceService._on_event` does not, so every worker workflow buffers spans
  in the **web** process as well, and nothing there ever ends them.
- **API-07** — three routes answer `200` with an error inside, two of them echoing the
  raw driver exception, against an `API.md` that says every error is `{"detail": …}` at
  a 4xx/5xx status.
- **KNOW-09** — `complete_step` is called for twelve step names and `done` is consulted
  for five. Three of the writes carry comments explaining that a resume must re-run a
  failed step; no resume reads those names, so the guard is inert in both directions.
  Two of the twelve are ungated *deliberately* (in-memory state, graph merge), which is
  why this is about the comments as much as the code.
- **TEST-02** — downgraded by its own verifier from high to low: the gate is not blind
  to a dead dense leg. What survives is that the golden-set metrics carry no dense-leg
  signal, so a reader cannot tell from them whether it ran.
"""

from __future__ import annotations

import datetime as dt
import textwrap

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def sched_db():
    import app.models  # noqa: F401  — registers every table on the metadata
    from app.models.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestTheClaimedSlotSurvivesTheRun:
    """OPS-11."""

    async def test_record_run_does_not_move_the_next_slot(self, sched_db) -> None:
        from app.models.scheduled_query import ScheduledQuery
        from app.services.scheduler_service import SchedulerService

        svc = SchedulerService()
        schedule = ScheduledQuery(
            id="s1",
            project_id="p1",
            user_id="u1",
            connection_id="c1",
            title="nightly",
            sql_query="SELECT 1",
            cron_expression="0 * * * *",
            is_active=True,
            next_run_at=_past(),
        )
        sched_db.add(schedule)
        await sched_db.commit()

        assert await svc.claim_due(sched_db, "s1", "0 * * * *") is True
        await sched_db.refresh(schedule)

        # A DISTINCTIVE slot, not the one `claim_due` just computed. With an hourly
        # cron both computations land on the same instant, so a `record_run` that
        # recomputes looks identical to one that leaves it alone — the first draft of
        # this test passed against exactly that defect. The reservation is what must
        # survive, whatever it happens to be.
        claimed = dt.datetime.now(dt.UTC) + dt.timedelta(days=3, minutes=17)
        schedule.next_run_at = claimed
        await sched_db.commit()

        await svc.record_run(sched_db, "s1", status="success")
        await sched_db.refresh(schedule)

        # SQLite returns a naive datetime; the INSTANT is what must survive, not the
        # tzinfo the driver drops on the round trip.
        stored = schedule.next_run_at
        if stored is not None and stored.tzinfo is None:
            stored = stored.replace(tzinfo=dt.UTC)
        assert stored == claimed, (
            "`claim_due` advances `next_run_at` atomically — that IS the multi-dyno "
            "guard — and `record_run` then recomputed it from the clock at completion "
            "time. A run that takes longer than one cron interval therefore skips the "
            "slot it had already reserved, and two dynos can disagree about which "
            "instant is next (OPS-11)"
        )

    async def test_the_run_row_and_timestamps_are_still_written(self, sched_db) -> None:
        """Leaving `next_run_at` alone must not stop `record_run` doing its job."""
        from app.models.scheduled_query import ScheduledQuery
        from app.services.scheduler_service import SchedulerService

        svc = SchedulerService()
        sched_db.add(
            ScheduledQuery(
                id="s2",
                project_id="p1",
                user_id="u1",
                connection_id="c1",
                title="n",
                sql_query="SELECT 1",
                cron_expression="0 * * * *",
                is_active=True,
                next_run_at=_past(),
            )
        )
        await sched_db.commit()

        run = await svc.record_run(sched_db, "s2", status="success", result_summary='{"rows": 1}')
        assert run.status == "success"
        schedule = await svc.get_schedule(sched_db, "s2")
        assert schedule.last_run_at is not None
        assert schedule.last_result_json == '{"rows": 1}'

    async def test_a_schedule_that_never_claimed_still_gets_a_next_slot(self, sched_db) -> None:
        """`run_now` records a run without claiming; that must not strand the schedule."""
        from app.models.scheduled_query import ScheduledQuery
        from app.services.scheduler_service import SchedulerService

        svc = SchedulerService()
        sched_db.add(
            ScheduledQuery(
                id="s3",
                project_id="p1",
                user_id="u1",
                connection_id="c1",
                title="n",
                sql_query="SELECT 1",
                cron_expression="0 * * * *",
                is_active=True,
                next_run_at=None,
            )
        )
        await sched_db.commit()

        await svc.record_run(sched_db, "s3", status="success")
        schedule = await svc.get_schedule(sched_db, "s3")
        assert schedule.next_run_at is not None, (
            "with no slot reserved there is nothing to preserve, and leaving NULL would "
            "take the schedule out of `get_due_schedules` for ever"
        )


class TestTheWebProcessDoesNotBufferTheWorkersSpans:
    """OPS-14."""

    def test_the_persistence_hook_ignores_a_rebroadcast(self) -> None:
        import inspect

        from app.services.trace_persistence_service import TracePersistenceService

        source = inspect.getsource(TracePersistenceService._on_event)
        assert "_external_rebroadcast" in source, (
            "`_deliver_local` runs every hook, including on the Redis rebroadcast path. "
            "`RunCoordinator._on_event` guards against exactly this; this one did not, "
            "so every `pipeline_start` a worker published created a buffer in the WEB "
            "process too — and nothing there ever ends it (OPS-14)"
        )

    async def test_a_rebroadcast_event_creates_no_buffer(self) -> None:
        from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
        from app.services.trace_persistence_service import TracePersistenceService

        tracker = WorkflowTracker()
        service = TracePersistenceService(tracker)
        event = WorkflowEvent(
            workflow_id="wf-from-the-worker",
            step="pipeline_start",
            status="started",
            detail="",
            pipeline="index_repo",
        )
        tracker._external_rebroadcast = True
        try:
            await service._on_event(event)
        finally:
            tracker._external_rebroadcast = False

        assert "wf-from-the-worker" not in service._buffers, (
            "the web process buffered spans for a workflow it is not running, and only "
            "a matching `pipeline_end` on the same process would ever free them"
        )

    async def test_a_local_event_still_creates_one(self) -> None:
        """The guard must not turn the service off."""
        from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
        from app.services.trace_persistence_service import TracePersistenceService

        service = TracePersistenceService(WorkflowTracker())
        await service._on_event(
            WorkflowEvent(
                workflow_id="wf-local",
                step="pipeline_start",
                status="started",
                detail="",
                pipeline="chat",
            )
        )
        assert "wf-local" in service._buffers


class TestAnErrorDoesNotArriveAsASuccess:
    """API-07."""

    @pytest.mark.parametrize(
        ("module", "function"),
        [
            ("app.api.routes.health_monitor", "reconnect_connection"),
            ("app.api.routes.notes", "execute_note"),
        ],
    )
    def test_the_raw_exception_is_not_returned_to_the_client(
        self, module: str, function: str
    ) -> None:
        """Read from the RETURN expressions, not from the source text.

        The first draft asserted `"str(exc)" not in source` and went red against the
        comment explaining the fix — the third time in this remediation that a guard
        matched its own prose. A `str()` call inside a `return` is the thing; a `str`
        in a sentence is not.
        """
        import ast
        import importlib
        import inspect

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(getattr(importlib.import_module(module), function)))
        )
        raw: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            for call in ast.walk(node.value):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "str":
                    raw.append(ast.unparse(call))
        assert not raw, (
            f"{module}.{function} returns {raw} — the unredacted driver exception, which "
            "on a failed connect is exactly the message most likely to carry a DSN, at "
            "a 200 status, against an `API.md` that says every error is "
            "`{'detail': …}` with a 4xx/5xx (API-07)"
        )

    def test_the_redactor_removes_the_credential(self) -> None:
        """The password, not the host — and the difference is deliberate.

        The first draft asserted the host was scrubbed too. It is not, and it should
        not be: the host is the caller's own configuration being echoed back to the
        person who entered it, and a message reading "could not connect to
        [redacted]" tells them nothing they can act on. What must never travel is the
        credential, which the caller did not type into this response and may not even
        know.
        """
        from app.core.redaction import safe_error

        message = safe_error(
            RuntimeError("could not connect to postgres://admin:hunter2@10.0.0.5:5432/db")
        )
        assert "hunter2" not in message, message
        assert "10.0.0.5" in message, (
            "the host is what makes the error actionable for the person who "
            f"configured it: {message}"
        )


class TestAStepSaysWhetherItsCompletionIsRead:
    """KNOW-09.

    `complete_step` is called for twelve names and the completed-step set is consulted
    for five. That is not uniformly a defect — `ast_parse` and `graph_build` are ungated
    on purpose, because they rebuild in-memory state a resumed process does not have —
    but three of the writes carried comments explaining that a resume must re-run a
    failed step, and no resume ever read those names. The guard those comments described
    was inert in both directions, and a comment asserting a mechanism that does not
    exist is worse than none: the next reader trusts it.
    """

    @staticmethod
    def _written_and_read() -> tuple[set[str], set[str]]:
        import ast
        import inspect

        from app.knowledge import pipeline_runner

        tree = ast.parse(inspect.getsource(pipeline_runner))
        written: set[str] = set()
        read: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "complete_step":
                for value in [*node.args, *(kw.value for kw in node.keywords)]:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        written.add(value.value)
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
                if any(getattr(c, "id", None) == "done" for c in node.comparators):
                    read.add(node.left.value)
        return written, read

    def test_every_recorded_step_declares_its_intent(self) -> None:
        from app.knowledge.pipeline_runner import STEP_RESUME_INTENT

        written, _ = self._written_and_read()
        assert written == set(STEP_RESUME_INTENT), (
            f"recorded but undeclared: {sorted(written - set(STEP_RESUME_INTENT))}; "
            f"declared but never recorded: {sorted(set(STEP_RESUME_INTENT) - written)}. "
            "A step whose completion nobody can look up is how three comments came to "
            "describe a resume guard that does not exist (KNOW-09)"
        )

    def test_the_declaration_matches_what_the_resume_actually_reads(self) -> None:
        from app.knowledge.pipeline_runner import STEP_RESUME_INTENT

        _, read = self._written_and_read()
        declared_gated = {n for n, intent in STEP_RESUME_INTENT.items() if intent == "GATED"}
        assert declared_gated == read, (
            f"declared GATED but not read on resume: {sorted(declared_gated - read)}; "
            f"read on resume but declared UNGATED: {sorted(read - declared_gated)}"
        )

    def test_the_two_deliberately_ungated_steps_stay_ungated(self) -> None:
        """CLAUDE.md records this, and a test already fails if either joins the gated
        set — in-memory state and the graph merge are the reasons, not an oversight."""
        from app.knowledge.pipeline_runner import STEP_RESUME_INTENT

        assert STEP_RESUME_INTENT["ast_parse"] == "UNGATED"
        assert STEP_RESUME_INTENT["graph_build"] == "UNGATED"

    def test_no_comment_still_claims_a_resume_guard_for_an_ungated_step(self) -> None:
        import inspect

        from app.knowledge import pipeline_runner

        source = inspect.getsource(pipeline_runner)
        for claim in (
            "a resume would skip the rebuild",
            'resume would treat the failure as "done"',
        ):
            assert claim not in source, (
                f"{claim!r} describes a mechanism that does not exist for that step (KNOW-09)"
            )


def _past():
    import datetime as dt

    return dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
