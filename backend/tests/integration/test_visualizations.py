"""Integration tests for /api/visualizations render and export endpoints."""

import pytest


@pytest.mark.asyncio
class TestVisualizationExport:
    async def test_export_csv(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/export",
            json={
                "columns": ["id", "name"],
                "rows": [[1, "Alice"], [2, "Bob"]],
                "format": "csv",
            },
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        body = resp.text
        assert "Alice" in body

    async def test_export_json(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/export",
            json={
                "columns": ["id", "name"],
                "rows": [[1, "Alice"]],
                "format": "json",
            },
        )
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("content-type", "")

    async def test_export_xlsx(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/export",
            json={
                "columns": ["id", "name"],
                "rows": [[1, "Alice"]],
                "format": "xlsx",
            },
        )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "spreadsheet" in ct or "octet" in ct

    async def test_export_missing_data(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/export",
            json={"format": "csv"},
        )
        assert resp.status_code == 422

    async def test_export_empty_rows(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/export",
            json={
                "columns": ["id"],
                "rows": [],
                "format": "csv",
            },
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestVisualizationRender:
    async def test_render_table(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/render",
            json={
                "columns": ["id", "value"],
                "rows": [[1, 100], [2, 200]],
                "viz_type": "table",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    async def test_render_missing_fields(self, auth_client):
        resp = await auth_client.post(
            "/api/visualizations/render",
            json={},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestVisualizationAuth:
    async def test_viz_requires_auth(self, client):
        endpoints = [
            ("POST", "/api/visualizations/export"),
            ("POST", "/api/visualizations/render"),
        ]
        for method, url in endpoints:
            resp = await client.post(
                url,
                json={"columns": ["a"], "rows": [[1]], "format": "csv"},
            )
            assert resp.status_code == 401, f"{method} {url} should require auth"
