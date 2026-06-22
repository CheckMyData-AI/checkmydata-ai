"""Unit tests for Phase 2 event-driven ingestion helpers.

Covers the webhook signature verification, repo-index debounce/dedup in
``_spawn_repo_index``, and the auto index→sync chain dispatch in
``maybe_autostart_sync``.
"""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes import repos as repos_route

# ---------------------------------------------------------------------------
# Webhook signature verification (pure function)
# ---------------------------------------------------------------------------


def test_verify_github_signature_valid():
    secret = "topsecret"
    body = b'{"ref":"refs/heads/main"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-hub-signature-256": f"sha256={digest}"}
    assert repos_route._verify_webhook_signature(secret, body, headers) is True


def test_verify_github_signature_tampered():
    secret = "topsecret"
    body = b'{"ref":"refs/heads/main"}'
    headers = {"x-hub-signature-256": "sha256=deadbeef"}
    assert repos_route._verify_webhook_signature(secret, body, headers) is False


def test_verify_gitlab_token_valid():
    secret = "gl-secret"
    headers = {"x-gitlab-token": "gl-secret"}
    assert repos_route._verify_webhook_signature(secret, b"{}", headers) is True


def test_verify_gitlab_token_mismatch():
    headers = {"x-gitlab-token": "wrong"}
    assert repos_route._verify_webhook_signature("gl-secret", b"{}", headers) is False


def test_verify_signature_empty_secret_fails_closed():
    body = b"{}"
    digest = hmac.new(b"", body, hashlib.sha256).hexdigest()
    headers = {"x-hub-signature-256": f"sha256={digest}"}
    assert repos_route._verify_webhook_signature("", body, headers) is False


def test_verify_signature_no_recognised_header():
    assert repos_route._verify_webhook_signature("s", b"{}", {}) is False


# ---------------------------------------------------------------------------
# _spawn_repo_index — dedup + debounce
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_repo_state():
    repos_route._indexing_tasks.clear()
    repos_route._index_start_locks.clear()
    repos_route._indexing_locks.clear()
    repos_route._last_index_trigger_at.clear()
    yield
    repos_route._indexing_tasks.clear()
    repos_route._last_index_trigger_at.clear()


@pytest.mark.asyncio
async def test_spawn_repo_index_skips_when_already_running():
    project = SimpleNamespace(id="p1", repo_url="git@x:y.git", repo_branch="main")

    class _NotDone:
        def done(self):
            return False

    repos_route._indexing_tasks["p1"] = _NotDone()  # type: ignore[assignment]

    result = await repos_route._spawn_repo_index(
        AsyncMock(), "p1", project, force_full=False, trigger="webhook", debounce=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_spawn_repo_index_debounces_recent_trigger():
    import time

    project = SimpleNamespace(id="p2", repo_url="git@x:y.git", repo_branch="main")
    # Pretend a trigger just happened.
    repos_route._last_index_trigger_at["p2"] = time.monotonic()

    with patch.object(repos_route.settings, "webhook_debounce_seconds", 300):
        result = await repos_route._spawn_repo_index(
            AsyncMock(), "p2", project, force_full=False, trigger="poll", debounce=True
        )
    assert result is None


@pytest.mark.asyncio
async def test_spawn_repo_index_enqueues_in_arq_mode():
    project = SimpleNamespace(id="p3", repo_url="git@x:y.git", repo_branch="main")

    db = AsyncMock()
    checkpoint_svc = AsyncMock()
    checkpoint_svc.get_active = AsyncMock(return_value=None)

    fake_run = SimpleNamespace(id="run-x", workflow_id="wf-x")

    with (
        patch.object(repos_route.task_queue, "is_arq_active", return_value=True),
        patch.object(repos_route.task_queue, "enqueue", new=AsyncMock()) as enq,
        patch.object(repos_route, "_checkpoint_svc", checkpoint_svc),
        patch(
            "app.services.run_coordinator.RunCoordinator.start",
            new=AsyncMock(return_value=fake_run),
        ),
    ):
        result = await repos_route._spawn_repo_index(
            db, "p3", project, force_full=True, trigger="manual"
        )

    assert result is not None
    assert result["status"] == "queued"
    assert result["run_id"] == "run-x"
    assert result["workflow_id"] == "wf-x"
    enq.assert_awaited_once()
    _, kwargs = enq.call_args
    assert kwargs["project_id"] == "p3"
    assert kwargs["force_full"] is True
    assert kwargs["wf_id"] == "wf-x"


# ---------------------------------------------------------------------------
# Auto index→sync chain dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_autostart_sync_dispatches_when_indexed():
    from app.api.routes import connections as conn_route

    conn_route._sync_tasks.clear()
    conn_route._sync_start_locks.clear()

    session = AsyncMock()

    class _FakeFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with (
        patch("app.models.base.async_session_factory", _FakeFactory()),
        patch.object(conn_route._sync_svc, "get_sync_status", AsyncMock(return_value="idle")),
        patch.object(conn_route._sync_svc, "set_sync_status", AsyncMock()),
        patch.object(conn_route._db_index_svc, "is_indexed", AsyncMock(return_value=True)),
        patch.object(conn_route, "_dispatch_code_db_sync", AsyncMock()) as disp,
    ):
        started = await conn_route.maybe_autostart_sync("c1", "p1")

    assert started is True
    disp.assert_awaited_once_with("c1", "p1")


@pytest.mark.asyncio
async def test_maybe_autostart_sync_skips_when_not_indexed():
    from app.api.routes import connections as conn_route

    conn_route._sync_tasks.clear()
    conn_route._sync_start_locks.clear()

    session = AsyncMock()

    class _FakeFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with (
        patch("app.models.base.async_session_factory", _FakeFactory()),
        patch.object(conn_route._sync_svc, "get_sync_status", AsyncMock(return_value="idle")),
        patch.object(conn_route._db_index_svc, "is_indexed", AsyncMock(return_value=False)),
        patch.object(conn_route, "_dispatch_code_db_sync", AsyncMock()) as disp,
    ):
        started = await conn_route.maybe_autostart_sync("c1", "p1")

    assert started is False
    disp.assert_not_awaited()
