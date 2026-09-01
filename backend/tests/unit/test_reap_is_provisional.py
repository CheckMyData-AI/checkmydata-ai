"""A reap is a guess, and two places treated it as a fact.

Measured in production on 2026-08-31, with every timestamp from the database:

| Time     | What happened                                          | Evidence |
|----------|--------------------------------------------------------|----------|
| 22:00:20 | schedule run `745c6ff3` starts (web dyno, in-process)  | `indexing_run_events` |
| 22:01:22 | `graph_build` starts                                   | event |
| 22:07:11 | that step is REAPED; the row flips to failed/REAP_ERROR| `error_log.last_seen_at` |
| 22:13:32 | the reaper's replacement starts (worker dyno, ARQ)     | event |
| 22:49:08 | `745c6ff3` emits `pipeline_end completed`               | event |

The reaped run was never dead. Two full repo indexes ran concurrently for 36 minutes on
the process this project documents as SIGKILLed at 1053 MiB against a 512 MiB quota.

Two defects made it possible, and each is sufficient alone:

1. The pipeline's heartbeat is a targeted UPDATE conditioned on `status == "running"`, so
   the moment the reaper flips the row the beat stops matching and the run can never
   re-assert liveness — the provisional verdict becomes self-fulfilling. A zero-row UPDATE
   raises nothing, so this was silent.
2. The duplicate guard reads STATUS, and status is exactly what the reaper falsified.
   `heartbeat_at` is the field that says something is alive, and nothing consulted it.

Mutual exclusion could not have caught it either: `_indexing_locks` is a module-level dict
of asyncio locks, so it is per-process, and these two runs were in different process types
(`daily_knowledge_sync_service` calls `run_repo_index_task` directly on web; the reaper
enqueues to ARQ on worker).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest


def _hb_source() -> str:
    """The body of the pipeline's heartbeat writer.

    Extracted by AST rather than by slicing N characters after `def _hb(`: the first
    version of this test took 900 characters, and adding the comment that explains WHY the
    status condition is gone pushed the code out of its own window — the test then failed
    saying the beat had moved.
    """
    import ast

    from app.knowledge import pipeline_runner

    src = inspect.getsource(pipeline_runner)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == "_hb":
            seg = ast.get_source_segment(src, node)
            if seg and "IndexingRun" in seg:
                return seg
    raise AssertionError("no _hb writing IndexingRun found; this test is reading stale code")


def _code_only(segment: str) -> str:
    """The segment with comment lines removed.

    Necessary, and the reason is a mistake this file already made: the comment explaining
    WHY `status == "running"` is gone contains that string verbatim, so a text search over
    the raw segment found the very thing it was asserting the absence of. Third time this
    session that prose tripped a text-based check — the suppression ratchet counted two of
    its own explanatory lines the same way.
    """
    return "\n".join(ln for ln in segment.splitlines() if not ln.lstrip().startswith("#"))


class TestTheBeatSurvivesAProvisionalReap:
    def test_the_beat_is_not_conditioned_on_status(self) -> None:
        """`status == "running"` in the beat's WHERE is what makes a wrong reap
        irreversible. The run is working; it must be able to say so."""
        body = _code_only(_hb_source())
        assert "heartbeat_at" in body
        assert 'status == "running"' not in body and "status=='running'" not in body, (
            "the beat only fires while the row says running, so a reaped-but-alive run "
            "can never re-assert liveness"
        )

    def test_a_beat_that_matches_no_row_is_logged(self) -> None:
        """A targeted UPDATE matching zero rows raises nothing. That silence is why the
        reason this run stopped beating could not be diagnosed from production data."""
        body = _code_only(_hb_source())
        assert "rowcount" in body, "nothing checks whether the beat landed"

    def test_the_log_dedup_flag_is_per_run_not_per_instance(self) -> None:
        """`PipelineRunner` outlives one run. A flag left on the instance would suppress
        the warning for the NEXT run's real gap — a silence caused by the fix for a
        silence."""
        from app.knowledge import pipeline_runner

        src = inspect.getsource(pipeline_runner)
        assert "self._beat_missed" not in src


class TestTheGuardReadsLivenessNotStatus:
    """`heartbeat_at` says something is alive. Status is what the reaper writes when it
    guesses — and only THAT guess is provisional."""

    @staticmethod
    def _live(status, beat, error=None):
        from app.services.run_coordinator import _is_live

        return _is_live(status, beat, timeout_seconds=300, error=error)

    def test_a_reaped_row_that_is_still_beating_blocks_a_second_run(self) -> None:
        """The production case. 22:13:32 minus 22:07:11 is 381 s, so with the beat surviving
        the reap the replacement sees a beat 21 s old and declines."""
        from app.services.stale_run_reaper import REAP_ERROR

        now = datetime.now(UTC)
        assert self._live("failed", now - timedelta(seconds=21), REAP_ERROR)

    def test_a_reaped_row_that_stopped_beating_does_not_block(self) -> None:
        """Otherwise a genuinely dead run would wedge the project forever."""
        from app.services.stale_run_reaper import REAP_ERROR

        now = datetime.now(UTC)
        assert not self._live("failed", now - timedelta(seconds=900), REAP_ERROR)

    @pytest.mark.parametrize("status", ["completed", "cancelled"])
    def test_a_finished_run_never_blocks_however_recent_its_beat(self, status: str) -> None:
        """A `completed` row reached an end and said so. The first version of this function
        treated any fresh beat as life, and the existing retry tests caught it: a run that
        finished two seconds ago blocked its own retry."""
        now = datetime.now(UTC)
        assert not self._live(status, now - timedelta(seconds=1))

    def test_a_run_that_failed_on_its_own_merits_never_blocks(self) -> None:
        """`failed` alone is a statement; only `failed` + REAP_ERROR is a guess."""
        now = datetime.now(UTC)
        assert not self._live("failed", now - timedelta(seconds=1), "boom")

    @pytest.mark.parametrize("status", ["running", "queued", "cancelling"])
    def test_a_non_terminal_row_is_active_even_before_its_first_beat(self, status) -> None:
        """A row created a moment ago has not been beaten yet; calling it dead would let
        two runs start in the same second, which is the race the guard was written for."""
        assert self._live(status, None)

    def test_a_naive_timestamp_does_not_raise(self) -> None:
        """SQLite stores no timezone, so dev and the entire test suite read this column
        back naive while the comparison is aware. Subtracting the two raises TypeError,
        which the first version did — caught by the existing coordinator tests."""
        from app.services.stale_run_reaper import REAP_ERROR

        naive = datetime.now(UTC).replace(tzinfo=None)
        assert self._live("failed", naive, REAP_ERROR) is True
