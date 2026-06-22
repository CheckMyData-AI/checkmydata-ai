"""P1: repo-index worker + task entrypoints accept a caller-provided wf_id."""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from app.api.routes import repos


def test_run_repo_index_task_accepts_wf_id():
    assert "wf_id" in inspect.signature(repos.run_repo_index_task).parameters


def test_run_repo_index_worker_accepts_wf_id(monkeypatch: pytest.MonkeyPatch):
    # ``arq`` is not installed in the unit-test venv; stub it so importing
    # ``app.worker`` (which evaluates WorkerSettings.redis_settings at module
    # load) does not fail. monkeypatch.setitem auto-reverts after the test.
    if "arq" not in sys.modules:
        arq_stub = types.ModuleType("arq")
        conn_stub = types.ModuleType("arq.connections")

        class _RedisSettings:
            @classmethod
            def from_dsn(cls, url: str) -> _RedisSettings:
                return cls()

        conn_stub.RedisSettings = _RedisSettings  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "arq", arq_stub)
        monkeypatch.setitem(sys.modules, "arq.connections", conn_stub)

    from app import worker

    assert "wf_id" in inspect.signature(worker.run_repo_index).parameters
