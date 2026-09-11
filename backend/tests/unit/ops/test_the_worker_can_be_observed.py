"""The background process was the one nobody could see (P1 row 11).

Seven findings, one process. The worker is where this product does its expensive, unattended
work — repository indexing, the nightly sync, analytics collection — and it is the process
this repository's own incident history names as the recurring failure surface. It was also
the one with no error reporting, no capability check, a maintenance loop that could not
reach its first tick, and a job ceiling equal to one of its own steps' budgets.

- **OPS-01** — `init_sentry()` is called at import time of `app/main.py`, which only the
  `web` dyno loads. `arq app.worker.WorkerSettings` never imports it, so **no background-job
  exception has ever reached Sentry**.
- **OPS-13** — the capability report's own docstring says *"silence is indistinguishable
  from the check not running"*, and a claim whose check **raises** was logged at DEBUG —
  invisible at production's INFO — while the summary still said "all satisfied". It also
  ran only on `web`, so the process whose capabilities matter most never reported them.
- **OPS-04** — `_maintenance_loop` sleeps `maintenance_interval_hours` (24 h) **before** its
  first tick, measured from process start, with no persistent marker. Heroku cycles dynos
  roughly daily, so billing reconcile, telemetry retention, the analytics journal prune and
  insight decay are gated behind uptime the platform does not grant.
- **OPS-09** — the BM25 reconcile's comment says it "never blocks the worker from taking
  jobs" and it is `await`ed inside `on_startup`, which arq completes before polling.
- **OPS-06** — `run_db_index` inherits the worker-wide 1800 s ceiling, which is exactly the
  budget of **one of its steps** (`db_index_fetch_samples_budget_seconds`).
- **OPS-15** — a Redis connect failure at boot permanently demotes the process to
  in-process execution, which is #330 by another route.
- **OPS-16** — the orphan sweep closes a run without `finished_at` or `failure_kind`.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from app import worker as worker_mod


def _startup_source() -> str:
    return textwrap.dedent(inspect.getsource(worker_mod.startup))


class TestTheWorkerReportsItsErrors:
    """OPS-01."""

    def test_startup_initialises_sentry(self) -> None:
        """The CALL. The name also appears on the import line, which is what the first
        draft matched — deleting the call left the import and the test green."""
        tree = ast.parse(_startup_source().replace("async def", "def", 1))
        calls = [
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("init_sentry")
        ]
        assert calls, (
            "`init_sentry()` runs at import time of app/main.py, which only the web dyno "
            "loads — so no exception from the repo index, the nightly sync or analytics "
            "collection has ever reached Sentry (OPS-01)"
        )


class TestTheWorkerReportsItsCapabilities:
    """OPS-13."""

    def test_startup_runs_the_capability_report(self) -> None:
        tree = ast.parse(_startup_source().replace("async def", "def", 1))
        calls = [
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("report_capabilities")
        ]
        assert calls, (
            "the capability report runs only on web, so the process whose capabilities "
            "decide whether indexing works never reports them"
        )

    def test_an_unevaluable_claim_is_not_logged_at_debug(self) -> None:
        """The level, not the sentence.

        The first draft asserted that the phrase "could not be evaluated" appears — and it
        does, inside the `logger.debug` call that IS the defect. A guard that matches the
        defect's own words passes on the defect.
        """
        from app.ops import capability_report

        tree = ast.parse(textwrap.dedent(inspect.getsource(capability_report)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = ast.unparse(node)
            if "could not be evaluated" not in body and "unevaluated" not in body:
                continue
            assert ".debug(" not in body, (
                "a claim whose check raises is logged at DEBUG — invisible at production's "
                "INFO — while the summary still says 'all satisfied', in a module whose own "
                "docstring says silence must not read as a pass (OPS-13)"
            )

    def test_an_unevaluable_claim_is_not_counted_as_satisfied(self) -> None:
        from app.ops import capability_report

        source = inspect.getsource(capability_report)
        assert "unevaluated" in source, (
            "nothing distinguishes a claim that passed from one that could not be checked, "
            "so the summary counts both as satisfied"
        )


class TestMaintenanceCanReachItsFirstTick:
    """OPS-04."""

    def test_the_loop_does_not_sleep_a_whole_interval_before_working(self) -> None:
        from app import main

        source = textwrap.dedent(inspect.getsource(main._maintenance_loop))
        tree = ast.parse(source.replace("async def", "def", 1))
        # Inside the `while`, not the function body — the function starts by computing the
        # interval, and the first DRAFT of this test read that assignment and passed.
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
        assert loops, "the maintenance loop is gone; this guard is blind"
        first_action = ast.unparse(loops[0].body[0])
        assert "sleep(interval_seconds)" not in first_action, (
            "the loop's first action is a full-interval sleep measured from process start, "
            "on a platform that restarts the dyno roughly daily — so billing reconcile, "
            "retention sweeps, the journal prune and insight decay never run (OPS-04)"
        )

    def test_it_remembers_when_it_last_ran(self) -> None:
        from app import main

        source = inspect.getsource(main._maintenance_loop)
        assert "deploy_state" in source or "last_run" in source or "marker" in source, (
            "nothing persists when maintenance last ran, so every restart starts the "
            "timer again and a daily restart means it never fires"
        )


class TestStartupDoesNotBlockJobPickup:
    """OPS-09."""

    def test_the_bm25_reconcile_is_not_awaited_in_startup(self) -> None:
        """`create_task` appearing SOMEWHERE in the module is not this call being detached.

        The first draft allowed exactly that and passed while the await was untouched.
        """
        tree = ast.parse(_startup_source().replace("async def", "def", 1))
        fn = tree.body[0]

        # `startup`'s OWN body. An await inside a nested coroutine that is then handed to
        # `create_task` is precisely the fix, and walking the whole tree cannot tell the two
        # apart — the second draft of this test failed against the correct code for that
        # reason.
        def _own_body(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                    continue
                yield child
                yield from _own_body(child)

        awaited = [
            ast.unparse(n)
            for n in _own_body(fn)
            if isinstance(n, ast.Await) and "reconcile_local_bm25" in ast.unparse(n)
        ]
        assert not awaited, (
            "the comment says this never blocks the worker from taking jobs, and it is "
            "awaited inside `on_startup`, which arq completes before it polls (OPS-09)"
        )


class TestLongJobsHaveTheirOwnCeiling:
    """OPS-06."""

    def test_db_index_does_not_inherit_a_ceiling_equal_to_one_of_its_steps(self) -> None:
        from app.config import settings

        # The REGISTRATION, found in the class body rather than by slicing after the first
        # occurrence of the name — which is the function's own `def`, and is what the first
        # draft of this test read.
        tree = ast.parse(inspect.getsource(worker_mod))
        settings_cls = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "WorkerSettings"
        )
        functions = next(
            ast.unparse(st.value)
            for st in settings_cls.body
            if isinstance(st, ast.Assign) and "functions" in ast.unparse(st.targets[0])
        )
        entry = next((line for line in functions.split(",") if "run_db_index" in line), "")
        assert "_arq_func_with_timeout" in entry, (
            "`run_db_index` inherits the worker-wide ceiling, which is "
            f"{settings.db_index_fetch_samples_budget_seconds} s — exactly the budget of "
            "one of its own steps, so the job is killed while that step is still within "
            "its allowance (OPS-06)"
        )
