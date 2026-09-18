"""C-04: the SSH key is resolved by id, and ownership is checked where it is attached.

`to_config` looked the key up **as the requester**, so every project member except the
person who uploaded it got a tunnel with no `client_keys` — reported as a problem with
the bastion, which is the one place it was not. And `PATCH /connections/{id}` verified
the MERGED key id, so renaming a connection whose key somebody else uploaded answered
404 naming a key the caller had never mentioned.

The rule, decided once: reaching a connection is authorised by project membership, and
the key is material that connection already references; **attaching** a key is the other
direction and still requires that the key be yours.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _generate_key() -> str:
    """A real key: the upload route parses it, and a fixture that cannot be parsed
    tests the parser rather than the ownership rule this file is about."""
    import asyncssh

    return asyncssh.generate_private_key("ssh-ed25519").export_private_key().decode()


_KEY = _generate_key()


async def _upload_key(client, token: str, name: str) -> str:
    resp = await client.post(
        "/api/ssh-keys",
        json={"name": name, "private_key": _KEY},
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _project_with_second_owner(client, db_session):
    """Two owners on one project. The membership is arranged directly: an INVITE cannot
    grant `owner`, and what this file is about is what happens once two people hold that
    role, not how the second one got it."""
    from app.services.membership_service import MembershipService

    owner = await register_user(client)
    second = await register_user(client)
    pid = (
        await client.post(
            "/api/projects", json={"name": "Two Owners"}, headers=auth_headers(owner["token"])
        )
    ).json()["id"]
    await MembershipService().add_member(db_session, pid, second["user_id"], role="owner")
    await db_session.commit()
    return owner, second, pid


@pytest.mark.asyncio
class TestAKeyBelongsToOnePersonAConnectionToAProject:
    async def test_another_owner_may_edit_a_connection_keyed_by_someone_else(
        self, client, db_session
    ):
        owner, second, pid = await _project_with_second_owner(client, db_session)
        key_id = await _upload_key(client, owner["token"], f"owner key {uuid.uuid4().hex[:8]}")
        cid = (
            await client.post(
                "/api/connections",
                json={
                    "project_id": pid,
                    "name": "Keyed Conn",
                    "db_type": "postgres",
                    "db_host": "10.0.0.5",
                    "db_name": "db",
                    "ssh_host": "bastion.example.com",
                    "ssh_user": "deploy",
                    "ssh_key_id": key_id,
                },
                headers=auth_headers(owner["token"]),
            )
        ).json()["id"]

        renamed = await client.patch(
            f"/api/connections/{cid}",
            json={"name": "Renamed by the other owner"},
            headers=auth_headers(second["token"]),
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Renamed by the other owner"

    async def test_attaching_a_key_that_is_not_yours_is_still_refused(self, client, db_session):
        owner, second, pid = await _project_with_second_owner(client, db_session)
        owner_key = await _upload_key(client, owner["token"], f"owner key {uuid.uuid4().hex[:8]}")
        cid = (
            await client.post(
                "/api/connections",
                json={
                    "project_id": pid,
                    "name": "Plain",
                    "db_type": "postgres",
                    "db_host": "10.0.0.5",
                    "db_name": "db",
                },
                headers=auth_headers(owner["token"]),
            )
        ).json()["id"]

        attached = await client.patch(
            f"/api/connections/{cid}",
            json={"ssh_key_id": owner_key},
            headers=auth_headers(second["token"]),
        )

        assert attached.status_code == 404, attached.text

    async def test_the_key_reaches_the_tunnel_for_a_member_who_did_not_upload_it(
        self, client, db_session
    ):
        from app.models.connection import Connection
        from app.services.connection_service import ConnectionService

        owner, second, pid = await _project_with_second_owner(client, db_session)
        key_id = await _upload_key(client, owner["token"], f"owner key {uuid.uuid4().hex[:8]}")
        cid = (
            await client.post(
                "/api/connections",
                json={
                    "project_id": pid,
                    "name": "Tunnelled",
                    "db_type": "postgres",
                    "db_host": "10.0.0.5",
                    "db_name": "db",
                    "ssh_host": "bastion.example.com",
                    "ssh_user": "deploy",
                    "ssh_key_id": key_id,
                },
                headers=auth_headers(owner["token"]),
            )
        ).json()["id"]

        conn = await db_session.get(Connection, cid)
        config = await ConnectionService().to_config(db_session, conn, user_id=second["user_id"])

        # The second owner never uploaded this key; the tunnel still gets it, because the
        # connection references it and the project admitted the second owner.
        assert config.ssh_key_content, "the tunnel would start with no client_keys"
        assert config.ssh_key_content.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
