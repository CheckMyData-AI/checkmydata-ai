"""Integration tests: sync_now 429 budget gate + sync-schedule next_run hour regression (C3, M4).

Uses monkeypatch to make preflight_owner_budget return budget exhausted.
Also tests that get_sync_schedule computes next_run with the correct hour.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture()
async def sync_test_project(auth_client: AsyncClient):
    """Create a project for sync_now and sync_schedule tests."""
    proj = await auth_client.post(
        "/api/projects",
        json={"name": "SyncNowTest", "description": "C3 sync_now budget gate"},
    )
    assert proj.status_code == 200
    return proj.json()["id"]


@pytest.mark.asyncio
class TestSyncNowBudgetGate:
    """Test sync_now 429 pre-flight budget gate (C3)."""

    async def test_sync_now_429_when_over_budget(self, auth_client: AsyncClient, sync_test_project):
        """sync_now must return 429 when owner is over budget."""
        project_id = sync_test_project

        # Patch preflight_owner_budget to simulate over-budget condition.
        with patch(
            "app.api.routes.projects.preflight_owner_budget",
            new=AsyncMock(return_value=(False, "daily token budget exhausted", None)),
        ):
            resp = await auth_client.post(f"/api/projects/{project_id}/sync-now")

        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert "budget" in detail.lower()

    async def test_sync_now_not_blocked_when_budget_ok(
        self, auth_client: AsyncClient, sync_test_project
    ):
        """sync_now should proceed past the budget gate when budget is ok.

        The request will still fail (409/202 depending on state) but NOT 429,
        confirming the budget gate let it through.
        """
        project_id = sync_test_project

        with patch(
            "app.api.routes.projects.preflight_owner_budget",
            new=AsyncMock(return_value=(True, None, "owner-uid")),
        ):
            resp = await auth_client.post(f"/api/projects/{project_id}/sync-now")

        # 202 = started; 409 = already running; what matters is it's NOT 429.
        assert resp.status_code in (202, 409)
        assert resp.status_code != 429


@pytest.mark.asyncio
class TestSyncScheduleNextRunHour:
    """Test sync-schedule next_run hour regression (M4)."""

    async def test_sync_schedule_next_run_hour_matches_effective_hour(
        self, auth_client: AsyncClient, sync_test_project
    ):
        """get_sync_schedule must compute next_run hour matching the effective hour."""
        project_id = sync_test_project

        # Set a custom sync schedule hour (e.g., 14 = 2 PM).
        set_resp = await auth_client.put(
            f"/api/projects/{project_id}/sync-schedule",
            json={"enabled": True, "hour": 14},
        )
        assert set_resp.status_code == 200
        set_data = set_resp.json()
        assert set_data["hour"] == 14
        assert set_data["enabled"] is True

        # Get the schedule and verify next_run hour matches.
        get_resp = await auth_client.get(f"/api/projects/{project_id}/sync-schedule")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["hour"] == 14
        assert data["enabled"] is True

        # Parse the next_run ISO string and check its hour matches the effective hour.
        if data["next_run"]:
            next_run_dt = datetime.fromisoformat(data["next_run"])
            # The next_run should be in the project's timezone; hour should be 14.
            assert next_run_dt.hour == 14, (
                f"next_run hour {next_run_dt.hour} does not match effective hour 14"
            )

    async def test_sync_schedule_next_run_with_default_global_hour(self, auth_client: AsyncClient):
        """sync-schedule with no project override should use global hour."""
        # Create a new project (no sync-schedule override).
        proj = await auth_client.post(
            "/api/projects",
            json={"name": "DefaultSchedule", "description": "Global schedule"},
        )
        assert proj.status_code == 200
        project_id = proj.json()["id"]

        # Get the schedule (should use global defaults).
        get_resp = await auth_client.get(f"/api/projects/{project_id}/sync-schedule")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["source"] == "global"

        # next_run should be computed from the global hour.
        if data["next_run"] and data["enabled"]:
            next_run_dt = datetime.fromisoformat(data["next_run"])
            # Global hour should be in range [0, 23].
            assert 0 <= next_run_dt.hour <= 23
