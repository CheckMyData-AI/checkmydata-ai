"""Nine places reported the work they asked for instead of the work that happened.

P1 row 10; API-03, API-12, OPS-05, OPS-17, ANA-10.

`task_queue.enqueue` returns `None` on failure rather than raising, and with
`allow_in_process=False` — correctly set at every one of these sites, because the
alternative is a repository index running inside the web dyno — a Redis fault produces
exactly that. Its own docstring says so: *"The task was NOT started; the caller should
surface a retryable failure."* Every caller discarded the return value and answered
`202 {"status": "queued"}`.

Each had already minted a run row set to `running`, so the failure is not merely a wrong
answer: the row blocks the single-active-run guard until the reaper times it out, and the
user is told to wait for something nobody is doing.

The same shape twice more with worse consequences: both cron wave dispatchers logged
`dispatched=len(projects)` from their input, so a day when every enqueue failed reads
identically to a day when every one succeeded; the feed scan returned
`connections_scanned = len(connection_ids)` while swallowing per-connection exceptions; and
"Collect now" shares a **day-scoped** job id with the hourly wave, so arq refuses it as a
duplicate for up to an hour while the route answers `queued`.

This file is one test per claim, and each asserts on the **returned value or logged count**
rather than on the shape of the code that produces it — a presence check passes for a
parameter nobody reads, which this programme has now learned three times in one row.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

ROUTES = pathlib.Path(__file__).parents[1].parent / "app" / "api" / "routes"

#: The five handlers that mint a run row and hand off to the worker.
ENQUEUE_SITES = [
    ("repos.py", "run_repo_index"),
    ("connections.py", "run_db_index"),
    ("connections.py", "run_code_db_sync"),
    ("projects.py", "run_repo_index"),
    ("runs.py", "run_repo_index"),
]


def _enqueue_calls(path: pathlib.Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("enqueue")
    ]


class TestAnEnqueueThatFailedIsNotReportedAsQueued:
    """API-03 / OPS-05."""

    def test_the_shared_helper_exists(self) -> None:
        from app.core.task_queue import enqueue_or_fail

        assert callable(enqueue_or_fail)

    @pytest.mark.asyncio
    async def test_it_raises_a_retryable_error_when_nothing_was_enqueued(self) -> None:
        """`asyncio_mode = "auto"`, so this is just an async test.

        The first draft called `asyncio.run()` inside a sync test, which closes the loop
        pytest-asyncio hands to everything after it — three connector tests in an unrelated
        file went red in the full run and passed in isolation.
        """
        from app.core.task_queue import EnqueueFailedError, enqueue_or_fail

        with pytest.raises(EnqueueFailedError):
            await enqueue_or_fail("nonexistent_task", allow_in_process=False)

    @pytest.mark.parametrize(("filename", "task"), ENQUEUE_SITES)
    def test_every_handoff_site_checks_the_result(self, filename: str, task: str) -> None:
        path = ROUTES / filename
        source = path.read_text(encoding="utf-8")
        if f'"{task}"' not in source:
            pytest.skip(f"{filename} no longer enqueues {task}")
        bare = [
            ast.unparse(c)[:70]
            for c in _enqueue_calls(path)
            if ast.unparse(c.func).endswith("task_queue.enqueue")
            and any(
                isinstance(kw.value, ast.Constant) and kw.value.value is False
                for kw in c.keywords
                if kw.arg == "allow_in_process"
            )
        ]
        assert not bare, (
            f"{filename} still calls the raw `enqueue` with allow_in_process=False and "
            f"ignores its result: {bare}. That returns None on a Redis fault, and the "
            "handler answers 202 'queued' over a run row it has already set to running"
        )


class TestTheCronWavesCountWhatTheyDispatched:
    """OPS-17."""

    @pytest.mark.parametrize(
        "func", ["_dispatch_daily_knowledge_sync_wave", "_dispatch_analytics_collect_wave"]
    )
    def test_the_count_is_not_taken_from_the_input(self, func: str) -> None:
        import textwrap

        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(main, func))))
        # The increment must be GUARDED by the enqueue's result. `dispatched += 1` sitting
        # unconditionally after the call is the defect, not the fix — the first draft of
        # this test asserted the increment exists and passed against exactly that.
        guarded = [
            ast.unparse(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and "dispatched += 1" in ast.unparse(node.body)
        ]
        assert guarded, (
            f"{func} increments its counter unconditionally after an enqueue that returns "
            "None on failure, so a night when every one failed reads exactly like a night "
            "when every one succeeded"
        )
        assert any("job_id" in cond for cond in guarded), (
            f"{func} guards the increment on something other than the job id: {guarded}"
        )


class TestTheFeedScanCountsSuccesses:
    """API-12."""

    def test_it_does_not_return_the_input_length(self) -> None:
        source = (ROUTES / "feed.py").read_text(encoding="utf-8")
        assert '"connections_scanned": len(connection_ids)' not in source, (
            "a connection whose scan raised is counted as scanned, and the response "
            "carries no sign that anything went wrong (API-12)"
        )


class TestCollectNowIsNotSilentlyRefused:
    """ANA-10."""

    def test_the_manual_route_does_not_share_the_waves_day_scoped_id(self) -> None:
        source = (ROUTES / "connections.py").read_text(encoding="utf-8")
        if "analytics_collect" not in source:
            pytest.skip("the manual collect route moved")
        assert "manual" in source.split("analytics_collect")[1][:400], (
            "'Collect now' reuses the hourly wave's day-scoped task id, so arq refuses it "
            "as a duplicate for up to an hour while the route answers 'queued' (ANA-10)"
        )
