"""The manual re-index carries a full rebuild, and its ceiling has to cover one.

`run_repo_index_task` is the repo-index pipeline, and two ARQ jobs call it — but not
with the same work, which is where the first version of this file went wrong:

| Entry | Arguments it passes | Ceiling |
|---|---|---|
| nightly cron | `force_full=False, chain_sync=False` | 7200 s |
| the button | `force_full=True`, chain on | `repo_index_job_timeout_seconds` |

The cron's job is `run_daily_project_knowledge_sync`; the button's, reached through
`POST /api/projects/{id}/index`, is `run_repo_index`.

**Correction, 2026-08-27.** This file first read the cron's 42.4-minute `completed`
run as a full rebuild and concluded that "the same work fits under one ceiling and
not the other", so 3600 s would do. Both halves were wrong.
`daily_knowledge_sync_service._run_repo_index` passes `force_full=False` and
`chain_sync=False` — an *incremental* index with the code↔DB chain off, because the
cron runs that sync itself as a separate step. So 42.4 min was never a full
rebuild, and `repo < daily` was never an invariant; asserting it capped the manual
path below what a full rebuild needs.

What a full rebuild actually costs, from the tracker on the 11:34 run — the two
dominant steps, both scaling with repository size rather than with a wall clock:

    11:37:23  code_symbol_embed: started
    12:15:43  code_symbol_embed: completed      2 300 s  (38.3 min)
    12:18:07  generate_docs: started
    12:34:52  killed at the 3600 s ceiling, at document ~80 of 758
    15:51:39  pipeline_end, after two more attempts — 12 039 s of work in total

`generate_docs` is LLM-bound at roughly 4.8 documents a minute (80 documents in
16.75 minutes, measured twice), so 758 of them is about 2.6 hours on their own.
That is why the cron's path finishes and the button's does not: incrementally,
`generate_docs` regenerates only what changed — three minutes on 2026-08-26
against ~158 for the full set.

Measured twice before the number below was trusted:

    09:30  1800.02 s  TimeoutError    inside `_run_code_symbol_embed`
    11:34  3600.00 s  interrupted     inside `generate_docs`, doc ~80/758

**Why the knob existed and still did not help.** AUD-0819-20 added it on
2026-08-19 for exactly this failure and left the default at 1800 — the value just
measured as too small — noting that a repository needing longer could "say so
without a code edit". Nothing in production said so. A knob defaulting to the
known-bad value relocates a defect; and the registration test pinning
`{"timeout": 1800}` as a literal made that default look deliberate.

The same day's memory fix is inside the 2 300 s above and the link was never drawn:
`EMBEDDING_UPSERT_BATCH_SIZE` went 200 → 8, buying ~552 MiB with ~17 % more wall
clock — spent in the step that dominates the budget.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[3]

#: A full rebuild of the one real customer repository — 9 981 files, 758 documents —
#: summed from measured segments of the run that reached `pipeline_end` at 15:51:39
#: on 2026-08-27. Summed rather than one wall clock because the run was interrupted
#: twice by deploys, and a wall clock spanning an idle gap would overstate the work:
#:
#:      151 s  setup + ast_parse + graph_build
#:     2300 s  code_symbol_embed
#:      144 s  analyze_files + cross_file_analysis + graph_db_bridge
#:     9375 s  generate_docs, 758 documents at ~4.8/min across three segments
#:       69 s  embed_and_store + bm25 + the chained code↔DB sync
#:    ------
#:    12039 s  = 3.34 h
#:
#: NOT the cron's 42.4-minute run, which is an incremental index with the chain off
#: and was the mis-reading this file exists to correct.
MEASURED_FULL_REBUILD_SECONDS = 12039

_DEFAULTS = Settings.model_fields


def _default(name: str) -> int:
    return int(_DEFAULTS[name].default)


class TestTheCeilingClearsAFullRebuild:
    def test_it_clears_the_measurement(self) -> None:
        ceiling = _default("repo_index_job_timeout_seconds")
        assert ceiling > MEASURED_FULL_REBUILD_SECONDS, (
            f"a full rebuild measures {MEASURED_FULL_REBUILD_SECONDS} s and the manual "
            f"ceiling is {ceiling} s — the button cannot finish a rebuild at all"
        )

    def test_it_clears_it_with_headroom(self) -> None:
        """A ceiling set to the last measurement fails on the next commit. Both
        dominant steps scale with repository size: `code_symbol_embed` with the symbol
        count, `generate_docs` with the document count."""
        ceiling = _default("repo_index_job_timeout_seconds")
        measured = MEASURED_FULL_REBUILD_SECONDS
        assert ceiling >= measured * 1.25, (
            f"{ceiling} s leaves under 25 % headroom over a measured {measured} s"
        )


class TestTheTwoCeilingsCoverDifferentWork:
    """The first version of this file asserted `repo < daily` on the grounds that the
    daily sync *contains* a repo index. It does not contain this one.

    `daily_knowledge_sync_service._run_repo_index` calls
    ``run_repo_index_task(project_id, force_full=False, chain_sync=False, wf_id=...)``
    — incremental, and with the code↔DB chain off because the daily sync runs that
    sync itself as a separate step. So the cron's budget covers
    *incremental* repo index + DB index + sync, while the manual button's budget
    covers a *full* rebuild plus the chained sync. Different workloads; the ordering
    was not an invariant, and asserting it capped the manual path below what a full
    rebuild needs.

    What replaces it is the fact the ordering was standing in for: each ceiling is
    checked against the workload it actually carries.
    """

    def test_the_cron_runs_it_incrementally_and_without_the_chain(self) -> None:
        service = (BACKEND / "app" / "services" / "daily_knowledge_sync_service.py").read_text(
            encoding="utf-8"
        )
        call = service[service.index("await run_repo_index_task(") :][:200]
        assert "force_full=False" in call, (
            "the cron's index is no longer incremental — the two ceilings may now carry "
            "comparable work and this file's reasoning needs redoing"
        )
        assert "chain_sync=False" in call, (
            "the cron now chains the code↔DB sync, so its budget contains work the "
            "manual path's does too — re-derive both ceilings"
        )

    def test_the_manual_ceiling_covers_a_full_rebuild_plus_the_chain(self) -> None:
        """The manual path is the only one that runs `force_full=True` **and** chains
        the sync, so its ceiling is the one that must clear the whole thing."""
        ceiling = _default("repo_index_job_timeout_seconds")
        assert ceiling >= MEASURED_FULL_REBUILD_SECONDS, (
            f"a full rebuild measures {MEASURED_FULL_REBUILD_SECONDS} s and the manual "
            f"ceiling is {ceiling} s"
        )


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
