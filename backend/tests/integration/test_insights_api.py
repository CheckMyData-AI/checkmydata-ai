"""Integration tests for the Data Graph and Insights API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def project_id(auth_client: AsyncClient) -> str:
    resp = await auth_client.post(
        "/api/projects",
        json={"name": "insight-test", "description": "test"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


class TestDataGraphAPI:
    @pytest.mark.asyncio
    async def test_graph_summary_empty(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.get(f"/api/data-graph/{project_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_metrics"] == 0
        assert data["total_relationships"] == 0

    @pytest.mark.asyncio
    async def test_upsert_and_list_metrics(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.post(
            f"/api/data-graph/{project_id}/metrics",
            json={
                "name": "monthly_revenue",
                "description": "Total revenue per month",
                "category": "revenue",
                "unit": "USD",
            },
        )
        assert resp.status_code == 200
        metric_id = resp.json()["id"]

        resp = await auth_client.get(f"/api/data-graph/{project_id}/metrics")
        assert resp.status_code == 200
        metrics = resp.json()
        assert len(metrics) >= 1
        assert any(m["id"] == metric_id for m in metrics)

    @pytest.mark.asyncio
    async def test_add_relationship(self, auth_client: AsyncClient, project_id: str):
        r1 = await auth_client.post(
            f"/api/data-graph/{project_id}/metrics",
            json={"name": "revenue", "category": "revenue"},
        )
        r2 = await auth_client.post(
            f"/api/data-graph/{project_id}/metrics",
            json={"name": "ad_spend", "category": "cost"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

        resp = await auth_client.post(
            f"/api/data-graph/{project_id}/relationships",
            json={
                "metric_a_id": r1.json()["id"],
                "metric_b_id": r2.json()["id"],
                "relationship_type": "correlation",
                "strength": 0.7,
            },
        )
        assert resp.status_code == 200

        resp = await auth_client.get(f"/api/data-graph/{project_id}/relationships")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_delete_metric(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.post(
            f"/api/data-graph/{project_id}/metrics",
            json={"name": "to_delete"},
        )
        assert resp.status_code == 200
        metric_id = resp.json()["id"]

        resp = await auth_client.delete(f"/api/data-graph/{project_id}/metrics/{metric_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_metric(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.delete(f"/api/data-graph/{project_id}/metrics/nonexistent-id")
        assert resp.status_code == 404


class TestInsightsAPI:
    @pytest.mark.asyncio
    async def test_list_insights_empty(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.get(f"/api/insights/{project_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_insight_summary_empty(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.get(f"/api/insights/{project_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_active"] == 0

    @pytest.mark.asyncio
    async def test_create_and_list_insight(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.post(
            f"/api/insights/{project_id}",
            json={
                "insight_type": "anomaly",
                "severity": "warning",
                "title": "Revenue dropped 20%",
                "description": "Monthly revenue decreased from $100k to $80k",
                "recommended_action": "Investigate pricing changes",
                "expected_impact": "Recovery of $20k/month",
                "confidence": 0.75,
            },
        )
        assert resp.status_code == 200
        insight_id = resp.json()["id"]

        resp = await auth_client.get(f"/api/insights/{project_id}")
        assert resp.status_code == 200
        insights = resp.json()
        assert len(insights) >= 1
        assert any(i["id"] == insight_id for i in insights)

    @pytest.mark.asyncio
    async def test_confirm_insight(self, auth_client: AsyncClient, project_id: str):
        create_resp = await auth_client.post(
            f"/api/insights/{project_id}",
            json={
                "insight_type": "opportunity",
                "severity": "positive",
                "title": "High-LTV segment found",
                "description": "Users from Brazil convert 2x better",
                "confidence": 0.6,
            },
        )
        assert create_resp.status_code == 200
        insight_id = create_resp.json()["id"]

        resp = await auth_client.patch(
            f"/api/insights/{project_id}/{insight_id}/confirm",
            json={"feedback": "This is correct"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"
        assert resp.json()["confidence"] >= 0.6

    @pytest.mark.asyncio
    async def test_dismiss_insight(self, auth_client: AsyncClient, project_id: str):
        create_resp = await auth_client.post(
            f"/api/insights/{project_id}",
            json={
                "insight_type": "anomaly",
                "severity": "info",
                "title": "Minor fluctuation",
                "description": "A small change that is just noise",
                "confidence": 0.4,
            },
        )
        assert create_resp.status_code == 200
        insight_id = create_resp.json()["id"]

        resp = await auth_client.patch(
            f"/api/insights/{project_id}/{insight_id}/dismiss",
            json={"feedback": "Not relevant"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_resolve_insight(self, auth_client: AsyncClient, project_id: str):
        create_resp = await auth_client.post(
            f"/api/insights/{project_id}",
            json={
                "insight_type": "loss",
                "severity": "critical",
                "title": "Checkout drop at step 3",
                "description": "Losing $12k/month due to checkout friction",
                "confidence": 0.8,
            },
        )
        assert create_resp.status_code == 200
        insight_id = create_resp.json()["id"]

        resp = await auth_client.patch(
            f"/api/insights/{project_id}/{insight_id}/resolve",
            json={"feedback": "Fixed the checkout flow"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_insight(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.patch(
            f"/api/insights/{project_id}/nonexistent-id/confirm",
            json={},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_insight_invalid_type(self, auth_client: AsyncClient, project_id: str):
        resp = await auth_client.post(
            f"/api/insights/{project_id}",
            json={
                "insight_type": "invalid_type",
                "title": "Test",
                "description": "Test",
            },
        )
        assert resp.status_code == 422
