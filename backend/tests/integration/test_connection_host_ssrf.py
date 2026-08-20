"""F-CONN-04 at the route — the guard is only worth what the product calls.

The unit tests in `tests/unit/test_connection_host_guard.py` prove the rule. These prove
it runs, on the model that creates a connection **and** the one that moves it. That second
one is not redundant: guarded-on-create/free-on-PATCH is a shape this codebase has
produced four times in two days.
"""

import pytest


class TestTheRoutesActuallyCallIt:
    """A guard nothing calls is a guard nothing calls. The unit tests above prove the
    rule; these prove the product runs it, on both the model that creates a connection
    and the one that moves it."""

    @pytest.mark.asyncio
    async def test_create_refuses_a_metadata_host(self, auth_client):
        project = await auth_client.post("/api/projects", json={"name": "ssrf", "description": ""})
        assert project.status_code == 200, project.text

        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": project.json()["id"],
                "name": "meta",
                "db_type": "postgres",
                "db_host": "169.254.169.254",
                "db_port": 5432,
                "db_name": "app",
                "db_user": "u",
                "db_password": "p",
            },
        )

        assert resp.status_code == 422
        assert "metadata" in resp.text

    @pytest.mark.asyncio
    async def test_update_refuses_moving_a_connection_to_a_metadata_host(self, auth_client):
        """The create/PATCH asymmetry this codebase has produced four times already."""
        project = await auth_client.post("/api/projects", json={"name": "ssrf2", "description": ""})
        created = await auth_client.post(
            "/api/connections",
            json={
                "project_id": project.json()["id"],
                "name": "ok",
                "db_type": "postgres",
                "db_host": "10.0.0.5",
                "db_port": 5432,
                "db_name": "app",
                "db_user": "u",
                "db_password": "p",
            },
        )
        assert created.status_code == 200, created.text

        resp = await auth_client.patch(
            f"/api/connections/{created.json()['id']}",
            json={"db_host": "169.254.169.254"},
        )

        assert resp.status_code == 422
        assert "metadata" in resp.text

    @pytest.mark.asyncio
    async def test_an_ordinary_private_host_still_creates(self, auth_client):
        """The default. If this fails the guard has become the outage it avoids."""
        project = await auth_client.post("/api/projects", json={"name": "ok", "description": ""})

        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": project.json()["id"],
                "name": "normal",
                "db_type": "postgres",
                "db_host": "10.0.0.5",
                "db_port": 5432,
                "db_name": "app",
                "db_user": "u",
                "db_password": "p",
            },
        )

        assert resp.status_code == 200, resp.text
