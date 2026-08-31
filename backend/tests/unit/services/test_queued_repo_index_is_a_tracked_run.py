"""A repo index enqueued directly created no `IndexingRun`, so nothing could see it.

`run_repo_index_task` — the ARQ entrypoint — called `tracker.begin()` and nothing else
when no `wf_id` was handed in. The manual HTTP route mints an `IndexingRun` through
`RunCoordinator` before enqueueing, and the daily sync service mints its own, so both of
those are visible. The direct enqueue path was not, and that path is the one
`reconcile_embeddings` uses: every `force_full` rebuild a deploy triggers ran with no row
behind it.

Measured in production on 2026-08-31: a 12 091-second `force_full` rebuild ran to
completion — `graph_build` alone took 799 seconds and produced 67 527 edges — while
`SELECT … WHERE status IN ('running','queued')` returned **zero rows** throughout.

Four things need that row, and all four were silently absent:

- `StaleRunReaper` finds stalled work by scanning `IndexingRun`. No row, no reap — and
  no re-enqueue either, so the CB-OPS3 fix did not cover the case that motivated it.
- `RunCoordinator.step` writes `heartbeat_at` onto that row (N1). No row, no heartbeat.
- `/api/projects/{id}/sync-history` and the run listings read it, so a three-hour
  rebuild was invisible to the operator who triggered it.
- `RunAlreadyActiveError` deduplicates on it, so two enqueues for one project could both
  proceed.
"""

from __future__ import annotations

import inspect

from app.api.routes import repos


def test_the_queue_entrypoint_mints_a_run_rather_than_a_bare_workflow() -> None:
    source = inspect.getsource(repos.run_repo_index_task)
    assert "RunCoordinator" in source, (
        "run_repo_index_task still begins a bare workflow; a rebuild enqueued by "
        "reconcile_embeddings would again run with no IndexingRun behind it — "
        "unreapable, unheartbeated and invisible"
    )


def test_it_reuses_a_workflow_id_it_was_given() -> None:
    """The manual route already minted the run before enqueueing. Minting a second one
    here would produce two rows for one rebuild and trip the duplicate guard."""
    source = inspect.getsource(repos.run_repo_index_task)
    assert "if wf_id is None" in source, "the caller-supplied workflow id must still win"


def test_an_already_active_run_is_not_duplicated() -> None:
    """`RunCoordinator.start` raises `RunAlreadyActiveError` when one is live. The task
    must return rather than start a second rebuild of the same project — two concurrent
    `force_full` runs on the memory-constrained worker is how R14 becomes R15."""
    source = inspect.getsource(repos.run_repo_index_task)
    assert "RunAlreadyActiveError" in source


def test_the_trigger_says_where_it_came_from() -> None:
    """`trigger` separates a queued rebuild from a scheduled or manual one in the run
    table. Without it every reconcile-driven rebuild reads as 'manual', which is what an
    operator would search for when something unexpected ran for three hours."""
    source = inspect.getsource(repos.run_repo_index_task)
    assert '"queue"' in source or "'queue'" in source


def test_a_coordinator_failure_does_not_abandon_the_index() -> None:
    """The row is bookkeeping. A rebuild that would have succeeded must not be skipped
    because the row could not be written — the previous behaviour had no row at all and
    still indexed correctly, so falling back to that is strictly no worse."""
    source = inspect.getsource(repos.run_repo_index_task)
    assert "except Exception" in source or "tracker.begin" in source, (
        "there must be a path that still indexes when the run row cannot be created"
    )
