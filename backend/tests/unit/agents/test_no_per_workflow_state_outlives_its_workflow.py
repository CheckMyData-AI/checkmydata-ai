"""The sweep has one key, and one of two entry paths never set it.

B-04. `OrchestratorAgent` keeps seven per-workflow maps on an instance that
`chat.py` builds at module scope, so anything they hold lives as long as the dyno.
`_cleanup_stale_results` frees them, and it enumerates stale ids from `_wf_seen` —
a single timestamp per workflow, written by `_note_workflow_seen`.

That call sat beside the router, under a comment reading *"here because every workflow
reaches this line"*. Every workflow does not. Eight lines above it, `_check_pipeline_resume`
returns straight into `_resume_pipeline`, so a **resumed** run wrote its maps under a
workflow id the sweep had never heard of. `_wf_sql_results` holds full `QueryResult`s with
every row.

The same shape as ORCH-06, on the same path: the resume is a second implementation of the
tail, and it keeps being the one that misses what the fresh path has.

Two guards, because the two ways this breaks are different. A path can skip the stamp —
which is what happened — and a map can be added without being swept, which is the worry
B-04 was opened for.
"""

from __future__ import annotations

import ast
import pathlib

ORCH = pathlib.Path(__file__).resolve().parents[3] / "app" / "agents" / "orchestrator.py"
_TREE = ast.parse(ORCH.read_text(encoding="utf-8"))


def _function(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(_TREE):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone — this walk no longer measures anything")


def _declared_maps() -> set[str]:
    """Every per-workflow MAP assigned in `__init__`.

    Selected by its annotated type rather than by its name. The first version keyed on
    the `_wf_` prefix and picked up `_wf_sql_lock`, which is one `asyncio.Lock` shared by
    every workflow and has nothing to free — a false finding, and the kind that gets a
    guard disabled rather than obeyed.
    """
    init = _function("__init__")
    out: set[str] = set()
    for stmt in ast.walk(init):
        if not isinstance(stmt, ast.AnnAssign):
            continue
        target = stmt.target
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr.startswith("_wf_")
        ):
            continue
        annotation = ast.unparse(stmt.annotation)
        if annotation.startswith("dict["):
            out.add(target.attr)
    return out


def test_the_sweep_frees_every_map_that_exists() -> None:
    """An eighth map added without a line in the sweep leaks silently and for ever.

    `_wf_seen` is excluded: it is the sweep's key rather than one of the things swept,
    and it is popped in the same loop.
    """
    swept = {
        node.func.value.attr
        for node in ast.walk(_function("_cleanup_stale_results"))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "pop"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr.startswith("_wf_")
    }
    declared = _declared_maps()
    assert declared, "no per-workflow map found — the walk has stopped measuring"
    assert declared - swept == set(), (
        f"these per-workflow maps are never freed: {sorted(declared - swept)}. They live "
        "on an agent built at module scope, so an entry survives until the dyno restarts."
    )


def test_the_stamp_is_taken_before_anything_can_return() -> None:
    """The defect, stated as a position rather than as a presence.

    `_note_workflow_seen` was present the whole time. What was wrong is that it came
    after a `return`, so the resume path never reached it — and a test asserting merely
    that `run` calls it would have passed against exactly that.
    """
    run = _function("run")
    stamp_line = next(
        (
            node.lineno
            for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_note_workflow_seen"
        ),
        None,
    )
    assert stamp_line is not None, "`run` no longer stamps the workflow at all"

    earlier_returns = [
        node.lineno
        for node in ast.walk(run)
        if isinstance(node, ast.Return) and node.lineno < stamp_line
    ]
    assert not earlier_returns, (
        f"`run` can return at line(s) {earlier_returns} before stamping the workflow at "
        f"line {stamp_line}. Anything those paths write into a `_wf_*` map is unreachable "
        "by `_cleanup_stale_results`, which keys the sweep on that stamp."
    )
