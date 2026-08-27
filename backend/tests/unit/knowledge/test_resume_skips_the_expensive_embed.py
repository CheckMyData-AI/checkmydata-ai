"""A resume must not repay the most expensive step it already finished.

`_run_steps` reads the completed-step set once (`pipeline_runner.py:168`) and gates
exactly four steps on it: `detect_changes` (:265), `cleanup_deleted` (:481),
`project_profile` (:510) and `cross_file_analysis` (:648). `code_symbol_embed`
writes `complete_step` and **nothing reads it**, so every resume runs it again.

Measured in production on 2026-08-27, tracker timings from one full rebuild:

    11:37:23  code_symbol_embed: started
    12:15:43  code_symbol_embed: completed      2 300 s  (38.3 min)

That is the single most expensive step in the pipeline, and it is expensive by
design: `EMBEDDING_UPSERT_BATCH_SIZE` was cut 200 → 8 to keep the worker inside its
memory quota, trading ~17 % wall clock for ~552 MiB.

Consequence, observed the same day. A full rebuild of that repository needs about
two hours; the manual job's ceiling cut it off at 3 600 s inside `generate_docs`.
Resuming re-entered `code_symbol_embed` and spent the 38 minutes over again — so
attempt N+1 reached no further than attempt N, and no number of attempts could
finish the job. A ceiling raise alone cannot fix that; it only moves where the
loop stalls.

The pattern to copy is already in the same file: `generate_docs` resumes at
*document* granularity through `processed_doc_paths` (:970, "N already done"). This
step needs the coarse version of that at minimum — skip when the checkpoint says it
finished.

Deliberately NOT gated, and left alone: `ast_parse` re-runs because parsed files
live in memory rather than in the checkpoint (:555), and `graph_build` re-runs
because it merges into the stored graph so unchanged files survive.
"""

from __future__ import annotations

import re
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[3] / "app" / "knowledge" / "pipeline_runner.py"
SOURCE = PIPELINE.read_text(encoding="utf-8")


def _block(step: str, width: int = 1400) -> str:
    """The source around a step's `tracker.step(... "<step>" ...)` call."""
    idx = SOURCE.index(f'"{step}",')
    return SOURCE[max(0, idx - width) : idx + 400]


class TestTheExpensiveStepIsSkippedWhenAlreadyDone:
    def test_code_symbol_embed_consults_the_completed_set(self) -> None:
        block = _block("code_symbol_embed")
        assert re.search(r'"code_symbol_embed"\s+not\s+in\s+done', block), (
            "code_symbol_embed records completion and no one reads it — a resume "
            "repays 38 minutes and can never get past the step that cut it off"
        )

    def test_it_still_records_its_completion(self) -> None:
        """The skip is only sound while the write is there to be read."""
        assert 'complete_step(db, cp_id, "code_symbol_embed")' in SOURCE

    def test_the_flag_gate_survives_the_resume_gate(self) -> None:
        """`hybrid_retrieval_enabled` and a non-empty `parsed_files` still decide
        whether the step runs at all; the resume check is an addition, not a
        replacement."""
        block = _block("code_symbol_embed")
        assert "settings.hybrid_retrieval_enabled" in block
        assert "state.parsed_files" in block


class TestTheGatedSetIsExactlyWhatWasIntended:
    """A list of gated steps is a claim about which work is safe to skip. Asserting
    it means a future step that starts recording completion cannot quietly join or
    leave the set without this file saying so."""

    def test_every_step_that_should_be_skippable_is(self) -> None:
        for step in (
            "detect_changes",
            "cleanup_deleted",
            "project_profile",
            "cross_file_analysis",
            "code_symbol_embed",
        ):
            assert re.search(rf'"{step}"\s+(not\s+)?in\s+done', SOURCE), step

    def test_the_two_deliberate_re_runs_stay_ungated(self) -> None:
        """Skipping either would be a correctness bug, not a saving: `ast_parse`
        rebuilds in-memory state nothing else can supply, and `graph_build` merges
        into the stored graph."""
        for step in ("ast_parse", "graph_build"):
            assert not re.search(rf'"{step}"\s+(not\s+)?in\s+done', SOURCE), (
                f"{step} is now gated on the checkpoint — it re-runs by design, and "
                "skipping it leaves a later step reading empty state"
            )


def test_generate_docs_keeps_its_finer_grained_resume() -> None:
    """The reason this file argues for a coarse skip rather than against fine-grained
    resume: the fine-grained version already exists one step later, and is the shape
    `code_symbol_embed` should eventually take."""
    assert "processed_doc_paths" in SOURCE or "processed_paths" in SOURCE
