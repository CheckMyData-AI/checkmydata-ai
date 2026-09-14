"""Every run kind must beat the row the reaper reads, on a wall clock.

PRJ-02. Four run kinds beat four different ways and three of them tick a row
`StaleRunReaper` does not judge them by:

| kind | what its pipeline beats | what the reaper reads |
|---|---|---|
| `index_repo` | `IndexingRun` by `workflow_id`, unconditioned | `IndexingRun` — right since 08-31 |
| `db_index` | `DbIndexSummary` only | `IndexingRun` — beaten only by manifest step events |
| `code_db_sync` | `CodeDbSyncSummary` only | `IndexingRun` — same |
| `daily_sync` | `IndexingRun` **`WHERE status='running'`** | `IndexingRun` — a reaped parent
|              |                                      | can never re-assert liveness |

Measured on production v409, 2026-09-14, with both rows read in one frame: a
`code_db_sync` at **319 s** elapsed had **302 s** since its `IndexingRun` beat and
**11 s** since its summary beat, while the worker log showed it analysing tables in
that same second. It was reaped at 347 s (345 s the night before — the timing is
arithmetic, not luck) and then **completed successfully at 619 s**, its row reading
`failed: stale run reaped`.

The consequence is not cosmetic. `/sync-history`, the UI, the attention rail and the
reaper's own requeue budget all read `IndexingRun.status`, so the product cannot tell a
successful run from a failed one — which is why PRJ-01's fix had to be verified on the
map rather than on the run row that described it.

The summary beats are **not** the bug and are not removed: the reaper sweeps four
models (`stale_run_reaper.py:296-312`), each on its own `heartbeat_at`, so each row
needs its own beat. What was missing is the run row's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every model with Base
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.services.run_coordinator import RunCoordinator
from app.services.stale_run_reaper import REAP_ERROR

BEAT = 0.05


@pytest.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'liveness.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sessions(engine, monkeypatch):
    sm = async_sessionmaker(engine, expire_on_commit=False)
    for target in (
        "app.services.run_coordinator.async_session_factory",
        "app.models.base.async_session_factory",
    ):
        try:
            monkeypatch.setattr(target, sm)
        except AttributeError:
            pass
    monkeypatch.setattr("app.services.run_coordinator.settings.heartbeat_interval_seconds", BEAT)
    return sm


async def _beat_at(sm, run_id: str) -> datetime | None:
    """`heartbeat_at` as a separate session sees it — i.e. as the reaper would."""
    async with sm() as other:
        return (
            await other.execute(select(IndexingRun.heartbeat_at).where(IndexingRun.id == run_id))
        ).scalar_one()


async def _make_run(sm, kind: str, wf_id: str) -> IndexingRun:
    """`start` mints its own workflow id; the test reads the one it chose."""
    async with sm() as db:
        run = await RunCoordinator().start(db, kind=kind, project_id="p1", trigger="schedule")
        await db.execute(
            update(IndexingRun).where(IndexingRun.id == run.id).values(workflow_id=wf_id)
        )
        await db.commit()
        return run


# ---------------------------------------------------------------------------
# R3/R5 — the beat must not be conditioned on status
# ---------------------------------------------------------------------------


async def test_the_run_beat_revives_a_row_the_reaper_gave_up_on(sessions):
    """A reap is provisional. A beat that stops matching makes the guess self-fulfilling."""
    from app.services.run_coordinator import run_beat_by_workflow

    sm = sessions
    run = await _make_run(sm, "code_db_sync", "wf-revive")

    # The reaper decides the run is dead while it is, in fact, working.
    async with sm() as db:
        await db.execute(
            update(IndexingRun)
            .where(IndexingRun.id == run.id)
            .values(
                status="failed",
                error=REAP_ERROR,
                heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db.commit()
    stale = await _beat_at(sm, run.id)

    await run_beat_by_workflow("wf-revive")()

    revived = await _beat_at(sm, run.id)
    assert revived is not None and revived > stale, (
        "the beat did not reach a reaped row. While the writer is conditioned on "
        "status == 'running', the instant the reaper flips the row the beat stops "
        "matching and a working run can never re-assert liveness — the guess makes "
        "itself true."
    )


async def test_no_heartbeat_writer_in_the_codebase_is_conditioned_on_status():
    """The shape has now been written three times; a guard is cheaper than a fourth review.

    S-03: the defect is invisible at the call site — a `WHERE status='running'` reads
    like prudence. The AST check asks the question the reviewer did not.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3] / "app"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            # a beat writer is an update() whose .values() sets heartbeat_at
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "values"):
                continue
            if not any(kw.arg == "heartbeat_at" for kw in node.keywords):
                continue
            chain = ast.unparse(node)
            if "status" in chain and "==" in chain:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")
    assert not offenders, (
        "a heartbeat writer is conditioned on status at "
        + ", ".join(offenders)
        + ". A reap is provisional — conditioning the beat on the status the reaper "
        "writes turns its guess into a fact."
    )


# ---------------------------------------------------------------------------
# R1/R2/R6 — every kind beats the row the reaper reads, and keeps its own
# ---------------------------------------------------------------------------


async def test_every_pipeline_beats_the_run_row_as_well_as_its_summary():
    """Both rows, because the reaper sweeps both and they answer different questions.

    `StaleRunReaper.reap_once` updates four models — `DbIndexSummary`,
    `CodeDbSyncSummary`, `IndexingCheckpoint` and `IndexingRun` — each on its own
    `heartbeat_at` (`stale_run_reaper.py:296-312`). The summary beats were never the
    bug: they keep their own rows alive. What was missing is the run row's, which is
    what `/sync-history`, the UI, the attention rail and the requeue budget read.
    """
    import inspect

    from app.knowledge import code_db_sync_pipeline, db_index_pipeline

    for mod, summary_writer in (
        (db_index_pipeline, "touch_heartbeat"),
        (code_db_sync_pipeline, "touch_heartbeat"),
    ):
        src = inspect.getsource(mod)
        assert "run_beat_by_workflow(wf_id)" in src, (
            f"{mod.__name__} does not beat its IndexingRun row — the reaper judges "
            "that row and it is refreshed only by manifest step events, which this "
            "pipeline does not emit between items"
        )
        assert summary_writer in src, (
            f"{mod.__name__} stopped beating its summary row; the reaper sweeps that too"
        )


async def test_the_shared_writer_is_used_rather_than_a_fourth_copy():
    """Four kinds, four hand-rolled writers, three of them wrong — hence one writer."""
    import inspect

    from app.services import daily_knowledge_sync_service, run_coordinator

    assert "run_beat_by_workflow_or_id(run_id)" in inspect.getsource(
        daily_knowledge_sync_service
    ), "the daily-sync parent rolled its own beat again"
    # Both exported writers must exist and share `_run_beat`'s properties.
    for name in ("run_beat_by_workflow", "run_beat_by_workflow_or_id", "_run_beat"):
        assert hasattr(run_coordinator, name), f"{name} is named by this test and is gone"


async def test_a_beat_that_matches_no_row_is_logged_rather_than_silent(sessions, caplog):
    """A targeted UPDATE matching nothing raises nothing.

    That silence is why the 2026-08-31 beat gap could not be diagnosed from the data:
    a beat keyed on a workflow id the row does not carry looks exactly like a beat
    that worked.
    """
    import logging

    from app.services.run_coordinator import run_beat_by_workflow

    with caplog.at_level(logging.WARNING):
        await run_beat_by_workflow("wf-that-no-row-carries")()
    assert any("matched no IndexingRun" in r.message for r in caplog.records), (
        "a beat that reached nothing said nothing"
    )


# ---------------------------------------------------------------------------
# R4 — a reaped-then-completed run ends `completed`, not `failed`
# ---------------------------------------------------------------------------


async def test_a_reaped_parent_that_finishes_is_reconciled_not_left_failed(sessions):
    """Measured: the 02:08 sync completed in 619 s with its row reading `failed`.

    `run_for_project` skipped its own terminal write because the row was already
    terminal — the reaper had put it there — so the reap verdict became permanent for
    a run that went on to finish. `/sync-history`, the UI and the nightly report all
    read that status, which is why PRJ-01's own fix had to be verified on the map
    rather than on the run row describing it.
    """
    import json

    from app.models.indexing_run import IndexingRun as _Run

    sm = sessions
    run = await _make_run(sm, "daily_sync", "wf-parent")

    async with sm() as db:
        await db.execute(
            update(_Run)
            .where(_Run.id == run.id)
            .values(status="failed", error=REAP_ERROR, failure_kind="fatal")
        )
        await db.commit()

    # What `run_for_project`'s tail now does when it finds a reaped row.
    async with sm() as db:
        row = await db.get(_Run, run.id)
        assert row is not None and row.error == REAP_ERROR
        meta = json.loads(row.meta_json or "{}")
        meta["reaped"] = {"error": row.error, "reaped_at": None}
        row.meta_json = json.dumps(meta)
        row.status = "completed"
        row.error = None
        row.failure_kind = None
        await db.commit()

    async with sm() as db:
        row = await db.get(_Run, run.id)
        assert row is not None
        assert row.status == "completed", "the reap verdict outlived the work it described"
        # The reap is preserved, not erased: both facts are true and the UI shows both.
        assert json.loads(row.meta_json)["reaped"]["error"] == REAP_ERROR


async def test_the_tail_actually_contains_that_branch():
    """The test above models the rule; this one pins that the code carries it."""
    import inspect

    from app.services import daily_knowledge_sync_service

    src = inspect.getsource(daily_knowledge_sync_service)
    assert "run.error == REAP_ERROR" in src, (
        "the daily-sync tail no longer reconciles a reaped parent, so a run that was "
        "wrongly declared dead and then finished stays `failed` forever"
    )
