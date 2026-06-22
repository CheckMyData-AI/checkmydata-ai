"""P1: repo-index worker + task entrypoints accept a caller-provided wf_id."""

from __future__ import annotations

import inspect

from app import worker
from app.api.routes import repos


def test_run_repo_index_worker_accepts_wf_id():
    assert "wf_id" in inspect.signature(worker.run_repo_index).parameters


def test_run_repo_index_task_accepts_wf_id():
    assert "wf_id" in inspect.signature(repos.run_repo_index_task).parameters
