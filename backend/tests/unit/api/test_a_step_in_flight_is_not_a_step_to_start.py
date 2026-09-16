"""One step's progress is not another step's state.

Reported from production on 2026-09-15, 21:33 UTC. The readiness rail showed
*"Database indexed — Run"* and *"Code ↔ DB synced — Run"* while the database said:

    code_db_sync_summary.sync_status   = completed   (synced_at 20:52)
    db_index_summary.indexing_status   = running     (heartbeat 21:35)

Two defects on one screen, and neither is about the data being wrong.

1. **A completed sync was invisible.** `is_synced` was consulted only inside
   `if indexed:` — so while an index ran, a sync that had finished forty minutes earlier
   read as not done. The step had no state of its own.
2. **A running index reported as "not indexed", with nothing to distinguish it from
   never-indexed.** So the rail offered a button to start what was already running; the
   second run is refused by `uq_indexing_runs_active_one`, and the click appears to do
   nothing at all.

The predicates answer three questions now — done, running, neither — and the rail reads
all three.
"""

from __future__ import annotations

import ast
import pathlib

PROJECTS = pathlib.Path(__file__).resolve().parents[3] / "app" / "api" / "routes" / "projects.py"


def _readiness_function() -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(PROJECTS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            body = ast.unparse(node)
            if "code_db_synced" in body and "db_indexed" in body:
                return node
    raise AssertionError("the readiness endpoint is gone — this walk measures nothing")


def test_the_sync_check_does_not_sit_inside_the_index_check() -> None:
    """The defect, stated as nesting rather than as a missing call.

    `is_synced` was always called. What was wrong is WHERE: inside the branch that had
    just established the index was complete, so a finished sync was unreachable whenever
    an index happened to be running. A test asserting the call exists would have passed.
    """
    fn = _readiness_function()
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.unparse(node.test)
        if "indexed" not in test_src or "not " in test_src:
            continue
        body_src = "\n".join(ast.unparse(stmt) for stmt in node.body)
        assert "is_synced" not in body_src, (
            "the sync check sits inside a branch guarded on the index being complete, so "
            "a finished sync is invisible whenever an index is running"
        )


def test_running_is_reported_as_its_own_state() -> None:
    """Without it, the caller can only choose between "done" and "offer a button"."""
    body = ast.unparse(_readiness_function())
    for name in ("is_indexing", "is_syncing", "db_indexing", "code_db_syncing"):
        assert name in body, (
            f"readiness no longer reports `{name}` — a step in flight is indistinguishable "
            "from one never started, and the rail offers to start it again"
        )


def test_a_running_step_is_not_offered_as_a_missing_step() -> None:
    """`missing_steps` is what the rail turns into buttons."""
    # Read from the parse rather than the source text: `ast.unparse` adds its own
    # parentheses, so matching the line as written is matching the formatter.
    fn = _readiness_function()
    guarded: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        appended = ast.unparse(node.body[0]) if node.body else ""
        if "missing_steps.append" not in appended:
            continue
        condition = ast.unparse(node.test)
        for step, running in (("index_db", "db_indexing"), ("sync", "code_db_syncing")):
            if f"'{step}'" in appended:
                assert running in condition, (
                    f"the `{step}` step is offered while `{running}` is true, so the rail "
                    "invites the user to start work already in flight — which the partial "
                    "unique index refuses, silently"
                )
                guarded.add(step)
    assert guarded == {"index_db", "sync"}, f"only guarded {sorted(guarded)}"
