"""A wrong call under a broad `except` is invisible forever.

The defect this closes, in full: `result_validation.py` incremented a Prometheus
counter with `metrics.increment(name, {...})` — written from memory. The real
method is `get_metrics_collector().inc(name, **labels)`. The call sat inside a
bare `except Exception: pass`, so the `AttributeError` was swallowed on every
request and the counter recorded nothing, permanently, while reading as
instrumented code.

Nothing could have caught it at runtime. The handler is correct in intent —
telemetry must never break a request — so the guard has to be static: bind every
call's arguments against the real signature and fail the suite on a mismatch.

**Receivers are resolved only where the expression names the type
unambiguously.** A first pass keyed on bare `tracker` and `metrics` too, and all
three of its hits were false: `metrics` in `app/eval/harness.py` is a dict, and
`tracker` in `knowledge_freshness_service.py` is a `GitTracker`. A checker that
cries wolf is one somebody switches off, so ambiguous names are out — the cost is
that a call through a locally-named receiver is not covered here.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.core.metrics import MetricsCollector
from app.core.workflow_tracker import WorkflowTracker

# Expression text -> the class it unambiguously denotes.
_RECEIVERS: dict[str, type] = {
    "get_metrics_collector()": MetricsCollector,
    "self._metrics": MetricsCollector,
    "self._tracker": WorkflowTracker,
    "self.tracker": WorkflowTracker,
}

_APP = pathlib.Path("app")


def _call_sites() -> list[tuple[pathlib.Path, ast.Call, type, str]]:
    out = []
    for path in sorted(_APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            cls = _RECEIVERS.get(ast.unparse(node.func.value))
            if cls is not None:
                out.append((path, node, cls, node.func.attr))
    return out


_SITES = _call_sites()


def test_the_sweep_actually_found_call_sites():
    """A binding check over zero sites is a green that proves nothing — the same
    shape as the retrieval eval that stayed green with its BM25 leg removed."""
    assert len(_SITES) > 100, (
        f"expected the telemetry receivers to be widely used, found {len(_SITES)}"
    )


@pytest.mark.parametrize(
    ("path", "node", "cls", "attr"),
    [pytest.param(*s, id=f"{s[0]}:{s[1].lineno}:{s[3]}") for s in _SITES],
)
def test_every_telemetry_call_binds_against_its_real_signature(path, node, cls, attr):
    method = getattr(cls, attr, None)
    assert method is not None, (
        f"{path}:{node.lineno} calls {cls.__name__}.{attr}(...), which does not exist. "
        "Under a broad except this records nothing, forever, while reading as instrumentation."
    )
    if any(k.arg is None for k in node.keywords):
        pytest.skip("**kwargs splat — the arguments are not knowable statically")

    kwargs = {k.arg: "<value>" for k in node.keywords if k.arg}
    positional = ["<self>"] + ["<arg>"] * len(node.args)
    try:
        inspect.signature(method).bind(*positional, **kwargs)
    except TypeError as exc:
        pytest.fail(f"{path}:{node.lineno} {cls.__name__}.{attr}(...) will raise at runtime: {exc}")
