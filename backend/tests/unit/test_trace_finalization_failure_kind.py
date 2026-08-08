"""An abnormally-ended run must record *how* it ended, not just that it did.

`finalize_trace` had no `failure_kind` parameter at all, which is why the column was
NULL on every abnormal close -- including the production trace of 2026-08-06
11:39:24, where a request that died on a database timeout was indistinguishable, in
the table, from one that crashed.
"""

from __future__ import annotations

import inspect

from app.services.trace_persistence_service import TracePersistenceService


def test_finalize_trace_accepts_a_failure_kind():
    sig = inspect.signature(TracePersistenceService.finalize_trace)
    assert "failure_kind" in sig.parameters, (
        "without this parameter the column can never be set from the route"
    )
    assert sig.parameters["failure_kind"].default is None


def test_both_abnormal_rest_paths_pass_a_kind_from_the_shared_vocabulary():
    """`transient | configuration | data_missing | fatal` — stage_executor.py's set."""
    import app.api.routes.chat as chat

    source = inspect.getsource(chat)
    assert 'failure_kind="transient"' in source, "the timeout path must say transient"
    assert 'failure_kind="fatal"' in source, "the crash path must say fatal"
    assert 'f"unknown-{session_id}"' not in source.replace('return f"unknown-{session_id}"', ""), (
        "the synthetic id must only be produced by the logged fallback helper"
    )


def test_finalize_does_not_overwrite_real_values_with_its_own_defaults():
    """The UPDATE must be additive, not a blanket overwrite.

    `_persist_workflow` writes the row at `pipeline_end` with real numbers -- the
    duration it measured and the LLM/DB call counts it derived from spans. The route
    then calls `finalize_trace` to attach chat metadata. When that UPDATE listed every
    column unconditionally, the *defaults of finalize_trace's parameters* won:
    `total_duration_ms=None`, `steps_used=0`, `route="unknown"`.

    Production trace 2026-08-06 11:39:24 is the proof it was not theoretical -- 84
    spans, `total_llm_calls=7` and `total_db_queries=10` survived (the UPDATE does not
    list them), while duration, steps and the routing signals did not.
    """
    import inspect

    from app.services.trace_persistence_service import TracePersistenceService

    source = inspect.getsource(TracePersistenceService.finalize_trace)
    update_block = source[source.index("if trace is not None:") : source.index("else:")]

    assert "values.update(" in update_block, "the UPDATE must be built conditionally"
    for clobbered in (
        "total_duration_ms=total_duration_ms",
        "steps_used=steps_used",
        "route=route",
        "complexity=complexity",
    ):
        assert clobbered not in update_block, (
            f"{clobbered} is written unconditionally again — a default would erase "
            "the value the buffer flush already measured"
        )
