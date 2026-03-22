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
