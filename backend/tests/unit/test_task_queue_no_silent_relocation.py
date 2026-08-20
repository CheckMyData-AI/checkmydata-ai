"""F-SCHED-04 — an ARQ enqueue failure quietly moved the job into the web dyno.

`enqueue()` has two modes and they were collapsed into one. With no `REDIS_URL` the
in-process `asyncio.create_task` path is the *intended* mode — that is how dev runs, and
the module says so. With Redis configured, an `enqueue_job` that throws is a production
incident: the code logged a **warning** and ran the job in the web process anyway.

For `run_repo_index` that is the pipeline measured at ~1 GB peak, executing inside the
dyno that serves user requests. It either OOMs the API or badly degrades latency, and the
only trace is one line at warning level.

The fix does not remove the fallback — it is right for light work and for dev. It
separates the two situations:

* **No Redis configured** → in-process, `INFO`, unchanged.
* **Redis configured, enqueue failed** → `ERROR`, because something is wrong with Redis
  and a warning is where that goes to die.
* **Redis configured, enqueue failed, and the caller says in-process is not a substitute**
  → refuse. Returning `None` makes the caller surface a failure the user can retry,
  which is a better outcome than a gigabyte silently relocating into the web dyno.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core import task_queue


@pytest.fixture(autouse=True)
def _clean_state():
    task_queue._fallback_tasks.clear()
    yield
    task_queue._fallback_tasks.clear()


async def _ran() -> str:
    return "ran in process"


class TestWithoutRedisNothingChanges:
    """In-process is the intended mode for dev; this is not the bug."""

    async def test_it_runs_in_process(self, caplog):
        with patch.object(task_queue, "_arq_pool", None):
            with caplog.at_level(logging.DEBUG):
                key = await task_queue.enqueue("run_repo_index", _ran, task_id="t1")

        assert key == "t1"
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    async def test_a_heavy_task_still_runs_in_process_without_redis(self):
        """The refusal is about Redis failing, not about the task being heavy. A
        deployment with no Redis has nowhere else to run it, and refusing would leave the
        feature simply broken."""
        with patch.object(task_queue, "_arq_pool", None):
            key = await task_queue.enqueue(
                "run_repo_index", _ran, task_id="t2", allow_in_process=False
            )

        assert key == "t2"


class TestWithRedisAFailureIsAnIncident:
    @pytest.fixture
    def failing_pool(self):
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(side_effect=ConnectionResetError("redis went away"))
        return pool

    async def test_the_failure_is_logged_at_error_not_warning(self, failing_pool, caplog):
        """A warning is where a broken Redis goes to die: production log level hides
        nothing at WARNING, but nobody alerts on it either."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            with caplog.at_level(logging.DEBUG):
                await task_queue.enqueue("run_db_index", _ran, task_id="t3")

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "an enqueue failure with Redis configured is not a warning"
        assert "run_db_index" in errors[0].getMessage()

    async def test_a_light_task_still_falls_back(self, failing_pool):
        """The fallback is not the bug. Removing it would turn a Redis blip into lost
        work for tasks that cost nothing to run here."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            key = await task_queue.enqueue("send_notification", _ran, task_id="t4")

        assert key == "t4"

    async def test_a_task_that_refuses_in_process_returns_none(self, failing_pool):
        """The finding: `run_repo_index` peaks near 1 GB. Running it in the web dyno is
        not a degraded version of running it in the worker — it is an outage with extra
        steps."""
        with patch.object(task_queue, "_arq_pool", failing_pool):
            key = await task_queue.enqueue(
                "run_repo_index", _ran, task_id="t5", allow_in_process=False
            )

        assert key is None
        assert "t5" not in task_queue._fallback_tasks

    async def test_the_refusal_says_which_task_and_why(self, failing_pool, caplog):
        with patch.object(task_queue, "_arq_pool", failing_pool):
            with caplog.at_level(logging.DEBUG):
                await task_queue.enqueue(
                    "run_repo_index", _ran, task_id="t6", allow_in_process=False
                )

        said = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "run_repo_index" in said
        assert "web" in said.lower() or "in-process" in said.lower()


#: Tasks whose in-process fallback is an outage rather than a degradation. `run_repo_index`
#: was measured at ~1 GB peak; the daily sync runs it plus the DB index plus the code↔DB
#: cross-reference.
HEAVY_TASKS = {
    "run_repo_index",
    "run_db_index",
    "run_code_db_sync",
    "run_daily_project_knowledge_sync",
}


def _heavy_enqueue_sites() -> list[tuple[str, int, str, bool]]:
    """Every `enqueue("<heavy task>", …)` in the app, and whether it passes the guard."""
    import ast

    app = Path(__file__).resolve().parents[2] / "app"
    out = []
    for f in sorted(app.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "enqueue"):
                continue
            if not (node.args and isinstance(node.args[0], ast.Constant)):
                continue
            name = node.args[0].value
            if name in HEAVY_TASKS:
                guarded = any(k.arg == "allow_in_process" for k in node.keywords)
                out.append((str(f), node.lineno, name, guarded))
    return out


class TestEveryHeavyCallSiteDeclaresIt:
    """Enumerated first, and the enumeration was wrong.

    The first version of this named three call sites by hand — the three the fix had
    touched — and passed. An AST sweep found **three more**: `projects.py` (manual
    sync-now), `runs.py` (a repo-index retry) and `main.py` (the daily-sync cron loop,
    which runs inside the web dyno, so an enqueue failure there put the entire daily sync
    in the process serving requests).

    A test written from the list of things you changed cannot tell you what you missed.
    This one is derived from the code.
    """

    def test_the_sweep_finds_call_sites_at_all(self):
        """A guard against the sweep silently matching nothing — then every assertion
        below would pass by vacuity."""
        assert len(_heavy_enqueue_sites()) >= 6

    def test_every_heavy_enqueue_refuses_in_process_execution(self):
        gaps = [
            f"{path}:{line} enqueues {name} without allow_in_process=False"
            for path, line, name, guarded in _heavy_enqueue_sites()
            if not guarded
        ]

        assert not gaps, (
            "an enqueue failure at these sites runs the job in the calling process — for "
            "the web dyno that is the pipeline measured at ~1 GB peak inside the process "
            "serving user requests:\n  " + "\n  ".join(gaps)
        )


class TestTheThreeSitesTheFixTouched:
    """Kept as named examples; the sweep above is the rule."""

    """A parameter nobody passes is a parameter that does nothing."""

    def test_repo_index_refuses_in_process(self):
        import inspect

        from app.api.routes import repos

        src = inspect.getsource(repos)
        idx = src.index('"run_repo_index"')
        assert "allow_in_process=False" in src[idx : idx + 400], (
            "the repo index is the job that was measured at ~1 GB; it must not relocate "
            "into the web dyno"
        )

    def test_db_index_refuses_in_process(self):
        import inspect

        from app.api.routes import connections

        src = inspect.getsource(connections)
        for marker in ('"run_db_index"', '"run_code_db_sync"'):
            idx = src.index(marker)
            assert "allow_in_process=False" in src[idx : idx + 400], marker


class TestFireAndForgetTasksAreHeld:
    """F-PROJ-05. asyncio keeps only a **weak** reference to a task, so one held by a
    local that dies with the request handler can be garbage-collected mid-flight — the
    hazard `chat.py`'s `_background_finalize_tasks` set was created for, in its own words:
    "losing the very results it was scheduled to save".

    The board recorded the symptom as silent death, and by the time it was read
    `spawn_tracked` already existed and already logged failures at `error`. What was left
    was the retention half, at the two places that launch a data investigation from a
    request and then return.
    """

    def test_no_route_launches_a_background_task_without_holding_it(self):
        """Asked as an AST question, because the text-window version was guesswork.

        A first attempt scanned 25 lines after the call for a retention marker and flagged
        three sites; two were false — `chat.py` awaits, polls and cancels its tasks 30 and
        130 lines later, which is structured concurrency rather than fire-and-forget. A
        window is an arbitrary number that will keep being wrong in both directions.

        The precise question: inside the enclosing function, is the assigned name used for
        anything other than attaching a done-callback? A task that is awaited, cancelled,
        polled or shielded has a lifetime. One that is assigned, given a callback and
        abandoned has only asyncio's weak reference, and the handler returning is what
        makes it collectable.
        """
        import ast

        routes = Path(__file__).resolve().parents[2] / "app" / "api" / "routes"
        offenders: list[str] = []

        for f in sorted(routes.rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for node in ast.walk(fn):
                    if not (
                        isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Call)
                        and getattr(node.value.func, "attr", None) == "create_task"
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                    ):
                        continue
                    name = node.targets[0].id
                    callback_lines = {
                        a.lineno
                        for a in ast.walk(fn)
                        if isinstance(a, ast.Attribute)
                        and a.attr == "add_done_callback"
                        and getattr(a.value, "id", None) == name
                    }
                    meaningful = [
                        u
                        for u in ast.walk(fn)
                        if isinstance(u, ast.Name)
                        and u.id == name
                        and u.lineno != node.lineno
                        and u.lineno not in callback_lines
                    ]
                    if not meaningful:
                        offenders.append(f"{f.name}:{node.lineno}")

        assert not offenders, (
            "these assign a task, attach a callback and return — leaving only asyncio's "
            f"weak reference. Use spawn_tracked: {offenders}"
        )
