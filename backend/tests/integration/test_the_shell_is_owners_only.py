"""C-02/C-12: a connection's shell is the owner's, and the form no longer writes one.

`ssh_command_template` and `ssh_pre_commands` are free-form shell run on the bastion,
and the connection form invited a password into them. Every project **viewer** could
read both through `GET /connections` and `GET /connections/{id}` — a role that cannot
change a connection could read the command line that reaches the database behind it.

The templates the server runs are not secret (they are constants in the source) and are
served read-only instead, so the form has no reason to keep its own copies — which were
the two shapes SQL-01 and F-SSH-02 removed: the password on the remote argv, and the SQL
on the client's stdin where `psql` reads `\\!` as a shell command.
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import auth_headers, register_user

_TEMPLATE = 'PGPASSWORD="$DBPASS" psql -h {db_host} -U {db_user} -d {db_name} -A'


async def _project_with_viewer(client) -> tuple[dict, dict, str, str]:
    owner = await register_user(client)
    viewer = await register_user(client)

    pid = (
        await client.post(
            "/api/projects", json={"name": "Shell Proj"}, headers=auth_headers(owner["token"])
        )
    ).json()["id"]

    invite = await client.post(
        f"/api/invites/{pid}/invites",
        json={"email": viewer["email"], "role": "viewer"},
        headers=auth_headers(owner["token"]),
    )
    await client.post(
        f"/api/invites/accept/{invite.json()['id']}",
        headers=auth_headers(viewer["token"]),
    )

    cid = (
        await client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Shell Conn",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
                "ssh_host": "bastion.example.com",
                "ssh_user": "deploy",
                "ssh_exec_mode": True,
                "ssh_command_template": _TEMPLATE,
                "ssh_pre_commands": ["export PATH=/usr/local/bin:$PATH"],
            },
            headers=auth_headers(owner["token"]),
        )
    ).json()["id"]
    return owner, viewer, pid, cid


@pytest.mark.asyncio
class TestTheShellIsOwnersOnly:
    async def test_the_owner_reads_the_command_it_runs(self, client):
        owner, _, pid, cid = await _project_with_viewer(client)

        one = await client.get(f"/api/connections/{cid}", headers=auth_headers(owner["token"]))
        listed = await client.get(
            f"/api/connections/project/{pid}", headers=auth_headers(owner["token"])
        )

        assert one.json()["ssh_command_template"] == _TEMPLATE
        assert listed.json()[0]["ssh_command_template"] == _TEMPLATE

    async def test_a_viewer_is_told_there_is_one_and_not_what_it_says(self, client):
        _, viewer, pid, cid = await _project_with_viewer(client)

        one = await client.get(f"/api/connections/{cid}", headers=auth_headers(viewer["token"]))
        listed = await client.get(
            f"/api/connections/project/{pid}", headers=auth_headers(viewer["token"])
        )

        for payload in (one.json(), listed.json()[0]):
            assert payload["ssh_command_template"] not in (_TEMPLATE, None)
            assert "psql" not in payload["ssh_command_template"]
            assert payload["ssh_pre_commands"] not in ("", None)
            assert "PATH" not in payload["ssh_pre_commands"]

    async def test_a_connection_without_a_template_says_so_to_everyone(self, client):
        owner = await register_user(client)
        viewer = await register_user(client)
        pid = (
            await client.post(
                "/api/projects", json={"name": "Plain"}, headers=auth_headers(owner["token"])
            )
        ).json()["id"]
        invite = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        await client.post(
            f"/api/invites/accept/{invite.json()['id']}", headers=auth_headers(viewer["token"])
        )
        cid = (
            await client.post(
                "/api/connections",
                json={
                    "project_id": pid,
                    "name": "Plain Conn",
                    "db_type": "postgres",
                    "db_host": "127.0.0.1",
                    "db_name": "testdb",
                },
                headers=auth_headers(owner["token"]),
            )
        ).json()["id"]

        payload = (
            await client.get(f"/api/connections/{cid}", headers=auth_headers(viewer["token"]))
        ).json()

        # Redaction must not invent a template where there is none: "no custom command"
        # is a fact a viewer is allowed to know, and the exec-mode UI reads it.
        assert payload["ssh_command_template"] is None
        assert payload["ssh_pre_commands"] is None


@pytest.mark.asyncio
class TestTheServerServesItsOwnTemplates:
    async def test_they_are_read_only_and_carry_no_password(self, auth_client):
        resp = await auth_client.get("/api/connections/exec-templates")

        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert {"postgres", "mysql", "clickhouse"} <= set(templates)
        for db_type, template in templates.items():
            assert "{db_password}" not in template, f"{db_type} would put the password in argv"
            assert "$DBPASS" in template or "PGPASSWORD" in template

    async def test_they_need_a_session(self, client):
        assert (await client.get("/api/connections/exec-templates")).status_code == 401


@pytest.mark.asyncio
class TestANewTemplateMayNotCarryThePassword:
    async def test_saving_one_is_refused(self, auth_client):
        pid = (await auth_client.post("/api/projects", json={"name": "Pwd Proj"})).json()["id"]

        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Pwd Conn",
                "db_type": "mysql",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
                "ssh_host": "bastion.example.com",
                "ssh_user": "deploy",
                "ssh_exec_mode": True,
                "ssh_command_template": 'mysql -u {db_user} --password "{db_password}" {db_name}',
            },
        )

        assert resp.status_code == 422
        assert "{db_password}" in resp.text

    async def test_one_without_it_is_accepted(self, auth_client):
        pid = (await auth_client.post("/api/projects", json={"name": "Ok Proj"})).json()["id"]

        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Ok Conn",
                "db_type": "mysql",
                "db_host": "127.0.0.1",
                "db_name": "testdb",
                "ssh_host": "bastion.example.com",
                "ssh_user": "deploy",
                "ssh_exec_mode": True,
                "ssh_command_template": "mysql -h {db_host} -u {db_user} {db_name} --batch",
            },
        )

        assert resp.status_code == 200
