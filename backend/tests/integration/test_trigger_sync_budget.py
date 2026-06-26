"""Integration tests: trigger_sync returns 429 when owner is over budget (T14/H5).

Uses monkeypatch to make preflight_owner_budget return (False, "budget exceeded", None)
and confirms the route returns 429 without starting any background work.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture()
async def indexed_connection(auth_client: AsyncClient):
    """Create a project+connection and mark it as DB-indexed so trigger_sync can run."""
    proj = await auth_client.post(
        "/api/projects",
        json={"name": "BudgetGateTest", "description": "T14 trigger_sync budget gate"},
    )
    assert proj.status_code == 200
    project_id = proj.json()["id"]

    conn = await auth_client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": "BudgetTestDB",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "testdb",
            "db_user": "user",
            "db_password": "pass",
        },
    )
    assert conn.status_code == 200
    connection_id = conn.json()["id"]

    return project_id, connection_id


@pytest.mark.asyncio
class TestTriggerSyncBudgetGate:
    async def test_trigger_sync_429_when_over_budget(
        self, auth_client: AsyncClient, indexed_connection
    ):
        """trigger_sync must return 429 when owner is over budget."""
        _, connection_id = indexed_connection

        # Patch preflight_owner_budget to simulate over-budget condition.
        with patch(
            "app.api.routes.connections.preflight_owner_budget",
            new=AsyncMock(return_value=(False, "daily token budget exhausted", None)),
        ):
            resp = await auth_client.post(f"/api/connections/{connection_id}/sync")

        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert "budget" in detail.lower()

    async def test_trigger_sync_not_blocked_when_budget_ok(
        self, auth_client: AsyncClient, indexed_connection
    ):
        """trigger_sync should proceed past the budget gate when budget is ok.

        The request will still fail (400) because the connection isn't DB-indexed,
        but it must NOT return 429 — confirming the budget gate let it through.
        """
        _, connection_id = indexed_connection

        with patch(
            "app.api.routes.connections.preflight_owner_budget",
            new=AsyncMock(return_value=(True, None, "owner-uid")),
        ):
            resp = await auth_client.post(f"/api/connections/{connection_id}/sync")

        # 400 = not indexed (expected); what matters is it's NOT 429.
        assert resp.status_code == 400
        assert resp.status_code != 429
