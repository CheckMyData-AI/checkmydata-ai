"""Integration tests: list endpoints enforce upper/lower bounds on limit/offset.

Covers qa-audit 02-api-contract N-2 remediation: notes, dashboards,
data-graph metrics/relationships and repos docs lists must reject
out-of-range pagination params with 422 and keep sane defaults working.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _make_project(auth_client) -> str:
    resp = await auth_client.post("/api/projects", json={"name": "Pagination Test"})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.parametrize("bad_limit", [-1, 0, 100000])
async def test_notes_list_limit_bounds(auth_client, bad_limit):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/notes?project_id={pid}&limit={bad_limit}")
    assert resp.status_code == 422


async def test_notes_list_offset_negative(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/notes?project_id={pid}&offset=-1")
    assert resp.status_code == 422


async def test_notes_list_defaults_and_slice(auth_client):
    pid = await _make_project(auth_client)
    for i in range(3):
        create = await auth_client.post(
            "/api/notes",
            json={"project_id": pid, "title": f"Note {i}", "sql_query": "SELECT 1"},
        )
        assert create.status_code == 200, create.text

    resp = await auth_client.get(f"/api/notes?project_id={pid}")
    assert resp.status_code == 200
    assert len(resp.json()) == 3

    resp = await auth_client.get(f"/api/notes?project_id={pid}&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = await auth_client.get(f"/api/notes?project_id={pid}&limit=2&offset=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.parametrize("bad_limit", [-1, 0, 100000])
async def test_dashboards_list_limit_bounds(auth_client, bad_limit):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/dashboards?project_id={pid}&limit={bad_limit}")
    assert resp.status_code == 422


async def test_dashboards_list_offset_negative(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/dashboards?project_id={pid}&offset=-1")
    assert resp.status_code == 422


async def test_dashboards_list_defaults_ok(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/dashboards?project_id={pid}")
    assert resp.status_code == 200


@pytest.mark.parametrize("bad_limit", [-1, 0, 100000])
async def test_data_graph_metrics_limit_bounds(auth_client, bad_limit):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/data-graph/{pid}/metrics?limit={bad_limit}")
    assert resp.status_code == 422


async def test_data_graph_metrics_defaults_ok(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/data-graph/{pid}/metrics")
    assert resp.status_code == 200


@pytest.mark.parametrize("bad_limit", [-1, 0, 100000])
async def test_data_graph_relationships_limit_bounds(auth_client, bad_limit):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/data-graph/{pid}/relationships?limit={bad_limit}")
    assert resp.status_code == 422


async def test_data_graph_relationships_offset_negative(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/data-graph/{pid}/relationships?offset=-1")
    assert resp.status_code == 422


@pytest.mark.parametrize("bad_limit", [-1, 0, 100000])
async def test_repos_docs_limit_bounds(auth_client, bad_limit):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/repos/{pid}/docs?limit={bad_limit}")
    assert resp.status_code == 422


async def test_repos_docs_offset_negative(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/repos/{pid}/docs?offset=-1")
    assert resp.status_code == 422


async def test_repos_docs_defaults_ok(auth_client):
    pid = await _make_project(auth_client)
    resp = await auth_client.get(f"/api/repos/{pid}/docs")
    assert resp.status_code == 200
    assert resp.json() == []
