"""Integration tests for /api/tasks/active tenancy."""

import pytest

from app.core.workflow_tracker import tracker


@pytest.mark.asyncio
async def test_active_requires_auth(client):
    resp = await client.get("/api/tasks/active")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_active_hides_other_users_workflows(auth_client):
    me = (await auth_client.get("/api/auth/me")).json()
    # Simulate another user's background workflow.
    other_wf = await tracker.begin(
        "index_repo",
        {"user_id": "someone-else", "project_id": "not-ours"},
    )
    try:
        resp = await auth_client.get("/api/tasks/active")
        assert resp.status_code == 200
        ids = [w["workflow_id"] for w in resp.json()]
        assert other_wf not in ids, (
            f"User {me['email']} should NOT see other users' workflows"
        )
    finally:
        await tracker.end(other_wf, "index_repo")


@pytest.mark.asyncio
async def test_active_shows_own_workflow(auth_client):
    me = (await auth_client.get("/api/auth/me")).json()
    mine = await tracker.begin(
        "index_repo",
        {"user_id": me["id"], "project_id": "proj"},
    )
    try:
        resp = await auth_client.get("/api/tasks/active")
        assert resp.status_code == 200
        ids = [w["workflow_id"] for w in resp.json()]
        assert mine in ids
    finally:
        await tracker.end(mine, "index_repo")
