"""Integration tests for /api/dashboards CRUD."""

import pytest

from tests.integration.conftest import auth_headers, register_user


@pytest.mark.asyncio
async def test_create_dashboard(auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    assert proj.status_code == 200
    project_id = proj.json()["id"]

    resp = await auth_client.post(
        "/api/dashboards",
        json={
            "project_id": project_id,
            "title": "My Dashboard",
            "layout_json": "{}",
            "cards_json": "[]",
            "is_shared": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == project_id
    assert data["title"] == "My Dashboard"
    assert data["id"]


@pytest.mark.asyncio
async def test_list_dashboards(auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    create = await auth_client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "Listed Dash"},
    )
    assert create.status_code == 200
    dash_id = create.json()["id"]

    resp = await auth_client.get(f"/api/dashboards?project_id={project_id}")
    assert resp.status_code == 200
    items = resp.json()
    assert any(d["id"] == dash_id and d["title"] == "Listed Dash" for d in items)


@pytest.mark.asyncio
async def test_update_dashboard(auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    create = await auth_client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "Original Title"},
    )
    assert create.status_code == 200
    dash_id = create.json()["id"]

    resp = await auth_client.patch(
        f"/api/dashboards/{dash_id}",
        json={"title": "Updated Title"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_delete_dashboard(auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    create = await auth_client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "To Delete"},
    )
    assert create.status_code == 200
    dash_id = create.json()["id"]

    del_resp = await auth_client.delete(f"/api/dashboards/{dash_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    get_resp = await auth_client.get(f"/api/dashboards/{dash_id}")
    assert get_resp.status_code == 404

    list_resp = await auth_client.get(f"/api/dashboards?project_id={project_id}")
    assert list_resp.status_code == 200
    assert not any(d["id"] == dash_id for d in list_resp.json())


@pytest.mark.asyncio
async def test_create_dashboard_no_auth(client, auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    client.headers.pop("Authorization", None)
    resp = await client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "No Token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_dashboard_no_project_membership(client, auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    other = await register_user(client)
    resp = await client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "Intruder"},
        headers=auth_headers(other["token"]),
    )
    assert resp.status_code == 403
    assert "member" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_dashboard_includes_user_role(auth_client):
    proj = await auth_client.post("/api/projects", json={"name": "Test"})
    project_id = proj.json()["id"]

    create = await auth_client.post(
        "/api/dashboards",
        json={"project_id": project_id, "title": "Role Check"},
    )
    dash_id = create.json()["id"]

    resp = await auth_client.get(f"/api/dashboards/{dash_id}")
    assert resp.status_code == 200
    assert resp.json()["user_role"] == "owner"


@pytest.mark.asyncio
class TestDashboardRBAC:
    """Verify role-based access for dashboard create/edit/delete."""

    async def _setup(self, client, db_session, owner_token, role):
        """Create project as owner, add a member with given role.

        Returns (project_id, member_token, owner_dash_id).
        """
        member = await register_user(client, db_session=db_session)

        resp = await client.post(
            "/api/projects",
            json={"name": "RBAC Test"},
            headers=auth_headers(owner_token),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": member["email"], "role": role},
            headers=auth_headers(owner_token),
        )
        invite_id = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(member["token"]),
        )
        assert resp.status_code == 200

        dash = await client.post(
            "/api/dashboards",
            json={"project_id": pid, "title": "Owner Dash", "is_shared": True},
            headers=auth_headers(owner_token),
        )
        assert dash.status_code == 200

        return pid, member["token"], dash.json()["id"]

    async def test_viewer_can_list_dashboards(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token, _ = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.get(
            f"/api/dashboards?project_id={pid}",
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 200

    async def test_viewer_cannot_create_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token, _ = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.post(
            "/api/dashboards",
            json={"project_id": pid, "title": "Viewer Dash"},
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_update_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token, dash_id = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.patch(
            f"/api/dashboards/{dash_id}",
            json={"title": "Hacked"},
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_delete_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token, dash_id = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.delete(
            f"/api/dashboards/{dash_id}",
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

    async def test_editor_can_create_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, editor_token, _ = await self._setup(
            client,
            db_session,
            owner_token,
            "editor",
        )
        resp = await client.post(
            "/api/dashboards",
            json={"project_id": pid, "title": "Editor Dash"},
            headers=auth_headers(editor_token),
        )
        assert resp.status_code == 200

    async def test_editor_can_update_any_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, editor_token, dash_id = await self._setup(
            client,
            db_session,
            owner_token,
            "editor",
        )
        resp = await client.patch(
            f"/api/dashboards/{dash_id}",
            json={"title": "Editor Updated"},
            headers=auth_headers(editor_token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Editor Updated"

    async def test_editor_can_delete_any_dashboard(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, editor_token, dash_id = await self._setup(
            client,
            db_session,
            owner_token,
            "editor",
        )
        resp = await client.delete(
            f"/api/dashboards/{dash_id}",
            headers=auth_headers(editor_token),
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestAnalyticsRBAC:
    """Verify analytics endpoints are owner-only."""

    async def _setup(self, client, db_session, owner_token, role):
        member = await register_user(client, db_session=db_session)

        resp = await client.post(
            "/api/projects",
            json={"name": "Analytics RBAC"},
            headers=auth_headers(owner_token),
        )
        pid = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": member["email"], "role": role},
            headers=auth_headers(owner_token),
        )
        invite_id = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(member["token"]),
        )
        assert resp.status_code == 200
        return pid, member["token"]

    async def test_owner_can_access_feedback_analytics(self, auth_client):
        proj = await auth_client.post("/api/projects", json={"name": "Test"})
        pid = proj.json()["id"]

        resp = await auth_client.get(f"/api/chat/analytics/feedback/{pid}")
        assert resp.status_code == 200

    async def test_viewer_cannot_access_feedback_analytics(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.get(
            f"/api/chat/analytics/feedback/{pid}",
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

    async def test_editor_cannot_access_feedback_analytics(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, editor_token = await self._setup(
            client,
            db_session,
            owner_token,
            "editor",
        )
        resp = await client.get(
            f"/api/chat/analytics/feedback/{pid}",
            headers=auth_headers(editor_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_access_validation_analytics(self, auth_client):
        proj = await auth_client.post("/api/projects", json={"name": "Test"})
        pid = proj.json()["id"]

        resp = await auth_client.get(f"/api/data-validation/analytics/{pid}")
        assert resp.status_code == 200

    async def test_viewer_cannot_access_validation_analytics(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, viewer_token = await self._setup(
            client,
            db_session,
            owner_token,
            "viewer",
        )
        resp = await client.get(
            f"/api/data-validation/analytics/{pid}",
            headers=auth_headers(viewer_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_access_analytics_summary(self, auth_client):
        proj = await auth_client.post("/api/projects", json={"name": "Test"})
        pid = proj.json()["id"]

        resp = await auth_client.get(f"/api/data-validation/summary/{pid}")
        assert resp.status_code == 200

    async def test_editor_cannot_access_analytics_summary(self, client, auth_client, db_session):
        owner_token = auth_client.headers["Authorization"].split()[-1]
        pid, editor_token = await self._setup(
            client,
            db_session,
            owner_token,
            "editor",
        )
        resp = await client.get(
            f"/api/data-validation/summary/{pid}",
            headers=auth_headers(editor_token),
        )
        assert resp.status_code == 403
