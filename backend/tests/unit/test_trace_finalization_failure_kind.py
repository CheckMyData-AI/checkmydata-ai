"""An abnormally-ended run must record *how* it ended, not just that it did.

`finalize_trace` had no `failure_kind` parameter at all, which is why the column was
NULL on every abnormal close -- including the production trace of 2026-08-06
11:39:24, where a request that died on a database timeout was indistinguishable, in
the table, from one that crashed.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from app.core.trace_meta import TraceMeta
from app.services.trace_persistence_service import TracePersistenceService


def test_the_failure_kind_travels_inside_a_required_record():
    """Inverted by Ш0, and the inversion is the finding.

    This asserted that `failure_kind` is a parameter defaulting to None. That
    default is exactly what let 10 of 12 call sites omit it and leave the column
    NULL in all 56 failed production traces. It now travels inside `TraceMeta`,
    which `finalize_trace` requires — a call that cannot be made without the
    value cannot forget it at a thirteenth entry point (#267's shape).
    """
    sig = inspect.signature(TracePersistenceService.finalize_trace)
    assert "failure_kind" not in sig.parameters, (
        "a loose kwarg beside meta would let a caller set one and not the other"
    )
    assert sig.parameters["meta"].default is inspect.Parameter.empty


def test_both_abnormal_rest_paths_pass_a_kind_from_the_shared_vocabulary():
    """`transient | configuration | data_missing | fatal` — now defined in ONE place.

    This test's own docstring named that set before `app/core/failure_kind.py`
    existed, and it enforced it by asserting the string literals at the call
    sites. That is why the vocabularies drifted: the knowledge lived in a test
    rather than in a module, so `chat.py` could write two of the four values and
    `stage_executor` could act on all four with nothing comparing them. The set
    was never unknown — it was unenforced.

    The literals are gone; the constants are what the call sites now name.
    """
    import app.api.routes.chat as chat
    from app.core.failure_kind import FAILURE_KINDS

    source = inspect.getsource(chat)
    assert "meta=TraceMeta.aborted(fk.TRANSIENT)" in source, "the timeout path must say transient"
    assert "meta=TraceMeta.aborted(fk.FATAL)" in source, "the crash path must say fatal"
    assert 'failure_kind="' not in source, (
        "a literal at the call site is what let the two vocabularies drift"
    )
    assert set(FAILURE_KINDS) == {"transient", "configuration", "data_missing", "fatal"}
    assert 'f"unknown-{session_id}"' not in source.replace('return f"unknown-{session_id}"', ""), (
        "the synthetic id must only be produced by the logged fallback helper"
    )


async def test_finalize_does_not_overwrite_real_values_with_its_own_defaults(monkeypatch):
    """The UPDATE must be additive, not a blanket overwrite.

    `_persist_workflow` writes the row at `pipeline_end` with real numbers -- the
    duration it measured and the call counts derived from spans. The route then calls
    `finalize_trace` to attach chat metadata. When that UPDATE listed every column
    unconditionally, the *defaults of finalize_trace's parameters* won:
    total_duration_ms=None erased 323 s, steps went to 0/0, route/complexity to
    "unknown" -- production trace 2026-08-06 11:39:24, which carried 84 real spans
    and still looked like a stub.

    Asserted on the emitted statement rather than on the source text: an earlier
    version of this test read the source, and a planted blanket-overwrite defect
    sailed straight through it.
    """
    from app.models.request_trace import RequestTrace
    from app.services import trace_persistence_service as tps

    captured: dict = {}

    class _Result:
        def scalar_one_or_none(self):
            return RequestTrace(id="t1", workflow_id="wf1", project_id="p", user_id="u")

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def execute(self, stmt):
            if stmt.__class__.__name__ == "Update":
                captured["values"] = {
                    c.name: getattr(v, "value", v) for c, v in stmt._values.items()
                }
            return _Result()

        async def commit(self):
            return None

    monkeypatch.setattr(tps, "async_session_factory", lambda: _Session())

    svc = tps.TracePersistenceService(tracker=MagicMock())
    await svc.finalize_trace(
        "wf1",
        project_id="p",
        user_id="u",
        response_type="error",
        status="failed",
        meta=TraceMeta.aborted("transient"),
    )

    written = captured["values"]
    assert written["response_type"] == "error"
    assert written["failure_kind"] == "transient"
    for erased in ("total_duration_ms", "steps_used", "steps_total", "route", "complexity"):
        assert erased not in written, (
            f"{erased} was written from a default and would erase what the buffer "
            "flush already measured"
        )
