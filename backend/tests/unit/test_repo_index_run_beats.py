"""A repo-index run must beat for as long as it works, from every entry point.

Measured on production 2026-09-08, and it is why the catch-up sync for the one real
project was killed by the reaper eleven minutes after it started:

    15:19:11  index_repo started
    15:20:00  last heartbeat_at written
    15:20:01  code_graph: built 408 symbols, 516 edges
    15:20:01  ...five minutes of worker silence, no restart, no R14/R15...
    15:25:10  status=failed, error='stale run reaped'

No process died. `builder.build` is already off the loop in `asyncio.to_thread`. What
was missing is simpler: **the run had no heartbeat at all.**

`RunCoordinator.step` is where the beat lives — it opens
`heartbeat(_run_beat(run.id), …)` around the work. `repos.py` calls
`RunCoordinator().start(...)` from both of its entry points and then runs the pipeline
*outside* any `step()`, so `IndexingRun.heartbeat_at` was written when the run began and
never again. The reaper's timeout is 300 s; any repo index whose remaining work exceeds
that is reaped while it is running, and the only reason some nightly runs completed is
that they happened to finish inside five minutes.

This is the same shape as N1 (2026-08-25), which is worth stating plainly: N1 put the
beat *inside* `RunCoordinator.step` because a step longer than the timeout was being
reaped mid-flight. It fixed the paths that go through `step`. The repo-index paths do
not go through `step`, so they never got the fix — and the failure stayed invisible for
the same reason it did the first time, because a *different* heartbeat exists nearby
(`IndexingCheckpoint`, ticked by `_run_index_background`) and the reaper reads
`IndexingRun`, a different row.
"""

from __future__ import annotations

import inspect
import re

from app.api.routes import repos


def _code_of(fn) -> str:
    """Source with docstrings and comments stripped.

    The prose in this file names the very thing it forbids, and a guard that trips on
    its own explanation gets the explanation deleted.
    """
    src = inspect.getsource(fn)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


class TestEveryRepoIndexEntryPointBeats:
    def test_the_queue_entry_point_reaches_the_beating_worker(self) -> None:
        """`run_repo_index_task` — the ARQ path, which runs the nightly and every
        deploy-triggered rebuild.

        It does not beat itself, and should not: it delegates to
        `_run_index_background`, which is the single place all four entry points
        converge and therefore the only sane home for one heartbeat. The property worth
        pinning is that the queue path goes *through* it rather than running the
        pipeline directly — the first version of this test asserted the literal word
        here and was simply wrong about where the beat belongs.
        """
        code = _code_of(repos.run_repo_index_task)
        assert "_run_index_background" in code, (
            "the queue path must run the pipeline through the worker that beats"
        )
        assert "_pipeline_runner.run" not in code, (
            "the queue path runs the pipeline directly, bypassing the heartbeat"
        )

    def test_the_background_worker_beats(self) -> None:
        """`_run_index_background` is where the pipeline actually runs, and it is reached
        from all four entry points (ARQ task, manual route, retry route, daily sync)."""
        code = _code_of(repos._run_index_background)
        assert "heartbeat" in code or "_run_beat" in code, (
            "the pipeline runs without a run-level heartbeat"
        )

    def test_it_beats_on_the_run_row_the_reaper_reads(self) -> None:
        """`IndexingCheckpoint` already had a tick, and it is not what the reaper reads.
        Getting this wrong is what hid the defect for thirteen days in August."""
        code = _code_of(repos._run_index_background)
        assert "_run_beat" in code, (
            "the beat must be `_run_beat(run_id)`, which updates IndexingRun — the row "
            "StaleRunReaper reads. Ticking IndexingCheckpoint instead is the August trap."
        )


class TestTheBeatSurvivesALongStep:
    async def test_a_step_longer_than_the_timeout_keeps_beating(self) -> None:
        """The property, not the wiring: work that outlasts the reaper's window must
        leave a fresher heartbeat behind than it started with.

        Uses the real `heartbeat` helper with a tiny interval and a recording writer, so
        this fails if the helper stops scheduling rather than only if `repos.py` forgets
        to call it.
        """
        import asyncio

        from app.core.heartbeat import heartbeat

        beats: list[int] = []

        async def _writer() -> None:
            beats.append(1)

        async with heartbeat(_writer, interval_seconds=0.01):
            await asyncio.sleep(0.15)

        assert len(beats) >= 3, (
            f"only {len(beats)} beat(s) during an awaiting step — a run doing this much "
            "work would be reaped as stale while alive"
        )
