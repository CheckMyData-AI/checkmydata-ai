"""The schedule endpoint reports whether it may run at all — executed, not grepped.

`SCN-147`. A source-grep test cannot tell a working route from one that raises
`NameError`, and it nearly did not have to: `projects.py` imports `select` inside each
function that needs it, the first version of this change used it at the top level of one
that did not, and every string-matching assertion in
`tests/unit/test_workspace_contract.py` still passed.

So this one calls the thing. Which is the whole argument for keeping both kinds: the
unit file pins the SHAPE of the contract cheaply, and this pins that it runs.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestSyncScheduleReportsMayRun:
    async def test_it_returns_may_run_for_a_real_project(self, auth_client) -> None:
        created = await auth_client.post(
            "/api/projects", json={"name": "sched-probe", "repo_branch": "main"}
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]

        resp = await auth_client.get(f"/api/projects/{pid}/sync-schedule")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "may_run" in body and isinstance(body["may_run"], bool)
        # Billing is off in tests, so the permissive default answers and automation is
        # allowed — the branch every self-hosted build depends on.
        assert body["may_run"] is True

    async def test_the_connection_card_is_told_the_capability(self, auth_client) -> None:
        """The other half of the workspace contract, also executed: `capability` is
        derived on the response model, so no route has to remember to fill it in."""
        project = (await auth_client.post("/api/projects", json={"name": "cap-probe"})).json()["id"]
        made = await auth_client.post(
            "/api/connections",
            json={
                "project_id": project,
                "name": "db",
                "db_type": "postgres",
                "db_host": "localhost",
                "db_port": 5432,
                "db_name": "x",
                "db_user": "u",
                "db_password": "p",
            },
        )
        assert made.status_code == 200, made.text
        assert made.json()["capability"] == "queryable"

        listed = await auth_client.get(f"/api/connections/project/{project}")
        assert listed.json()[0]["capability"] == "queryable"
