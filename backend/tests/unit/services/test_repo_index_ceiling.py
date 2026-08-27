"""One pipeline must not have two ceilings depending on which door it came through.

`run_repo_index_task` is the repo-index pipeline. Two ARQ jobs call it, and each
carries its own timeout:

| Entry | ARQ job | Setting carrying the ceiling |
|---|---|---|
| nightly cron | `run_daily_project_knowledge_sync` | `daily_knowledge_sync_job_timeout_seconds` |
| the button, `POST .../index` | `run_repo_index` | `repo_index_job_timeout_seconds` |

Measured on the one real customer repository in production, `indexing_runs` for
`kind='index_repo'`:

    08-25 22:00  completed  42.4 min   <- nightly, ceiling 7200 s
    08-27 09:30  TimeoutError 30.0 min <- manual,  ceiling 1800 s

    1800.02s ! 33f44e65d24b48bd9795717bc21b0285:run_repo_index failed, TimeoutError
      pipeline_runner.py:1468 in _run_code_symbol_embed

The same 2 544 s of work fits under one ceiling and cannot fit under the other, so
the repository rebuilds unattended at 3 a.m. and never rebuilds when a person asks
for it. That is the worse half: the manual button is what an operator reaches for
after a fix, and it is the path that cannot finish.

**This was diagnosed once already.** AUD-0819-20 gave the job its own knob on
2026-08-19 precisely because "production hit the hardcoded 1800 s with
`code_symbol_embed` still running after 29 minutes" — and left the default at the
value that had just been measured as too small, with a note that a repository
needing longer "can now say so without a code edit". Nobody said so; neither
`REPO_INDEX_JOB_TIMEOUT_SECONDS` nor its sibling is set in production. A knob whose
default is the known-bad value relocates the defect, it does not fix it.

The same day's memory fix made it worse and the connection was not drawn:
`EMBEDDING_UPSERT_BATCH_SIZE` was cut from 200 to 8, trading ~17 % wall clock for
~552 MiB. That 17 % is spent inside the step the ceiling now cuts off.

Two orderings are asserted below, and each fails differently. Losing the first
means the manual path cannot finish work the automatic path can. Losing the second
means the containing job would be cut off before the step it contains.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[3]

#: Longest full rebuild that ever *completed*, in seconds — `indexing_runs`, 42.4 min.
#: Runs longer than this on record all end `stale run reaped`, meaning their
#: heartbeat had stopped (the N1 defect, fixed 2026-08-25); their wall clock is
#: not evidence of work taking that long.
MEASURED_FULL_REBUILD_SECONDS = 2544

_DEFAULTS = Settings.model_fields


def _default(name: str) -> int:
    return int(_DEFAULTS[name].default)


class TestTheManualPathCanFinishWhatTheNightlyPathCan:
    def test_the_repo_index_ceiling_clears_the_measured_rebuild(self) -> None:
        ceiling = _default("repo_index_job_timeout_seconds")
        assert ceiling > MEASURED_FULL_REBUILD_SECONDS, (
            f"a full rebuild of the one real customer repository took "
            f"{MEASURED_FULL_REBUILD_SECONDS} s and the manual ceiling is {ceiling} s — "
            "the button cannot finish work the cron finishes"
        )

    def test_it_clears_it_with_headroom(self) -> None:
        """A ceiling set to the last measurement is a ceiling that fails on the next
        commit. The rebuild grows with the repository, and the memory fix already
        spends ~17 % of it."""
        ceiling = _default("repo_index_job_timeout_seconds")
        measured = MEASURED_FULL_REBUILD_SECONDS
        assert ceiling >= measured * 1.25, (
            f"{ceiling} s leaves under 25 % headroom over a measured {measured} s"
        )


class TestTheContainingJobOutlivesWhatItContains:
    """The daily sync runs the repo index, then the DB index, then the code↔DB sync,
    in one job. Its ceiling must therefore be strictly the larger one — if it were
    not, the cron would be cut off inside a step that was still within its own
    budget, and the failure would be attributed to the step."""

    def test_daily_sync_gets_the_larger_budget(self) -> None:
        repo = _default("repo_index_job_timeout_seconds")
        daily = _default("daily_knowledge_sync_job_timeout_seconds")
        assert daily > repo, f"daily sync {daily} s must exceed the repo index {repo} s it contains"

    def test_the_daily_sync_really_does_contain_it(self) -> None:
        """Asserted rather than assumed: the ordering above is only an invariant while
        one job calls the other. If the call goes away, this test says so instead of
        the ordering quietly becoming arbitrary."""
        service = (BACKEND / "app" / "services" / "daily_knowledge_sync_service.py").read_text(
            encoding="utf-8"
        )
        assert "run_repo_index_task" in service


class TestEveryLongJobHasAKnobAndNoneIsHardcoded:
    """`run_repo_index` was the only long job reading the class-level `job_timeout`,
    which is why it was the one that could not be raised without a deploy. The check
    is that no *registered* function is left in that position again."""

    def test_the_class_level_default_is_a_floor_not_a_ceiling_for_long_jobs(self) -> None:
        worker = (BACKEND / "app" / "worker.py").read_text(encoding="utf-8")
        block = worker[worker.index("    functions = [") :]
        block = block[: block.index("]")]
        for long_job in (
            "run_repo_index",
            "run_daily_project_knowledge_sync",
            "run_analytics_collect",
        ):
            line = next(ln for ln in block.splitlines() if long_job in ln)
            idx = block.index(line)
            window = block[max(0, idx - 120) : idx]
            assert "_arq_func_with_timeout" in window, (
                f"{long_job} is registered without its own timeout and inherits the "
                "hardcoded class-level job_timeout — the exact shape of AUD-0819-20"
            )

    def test_the_knob_is_reachable_from_the_environment(self) -> None:
        """A default nobody can override in production is a code edit per repository."""
        example = (BACKEND / ".env.example").read_text(encoding="utf-8")
        assert "REPO_INDEX_JOB_TIMEOUT_SECONDS" in example


def test_a_non_positive_ceiling_still_refuses_to_boot() -> None:
    """Raising the default must not disturb the guard that makes `0` an error rather
    than an accidental "no timeout"."""
    config = (BACKEND / "app" / "config.py").read_text(encoding="utf-8")
    assert re.search(
        r"if self\.repo_index_job_timeout_seconds <= 0:\s*\n\s*raise ValueError", config
    )
