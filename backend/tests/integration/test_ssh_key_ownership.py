"""Cross-tenant SSH private-key use — the hole carried from m0 as C13/K4.

The exploit does not steal the key; it makes the server *use* it.

1. `ssh_key_id` was accepted as a plain string on connection and project writes
   (`connections.py`, `projects.py`) with no check that the caller owns that key.
2. `SshKeyService.get()` filters by owner only when `user_id` is truthy.
3. `git_agent.py` and `knowledge/pipeline_runner.py` resolve `project.ssh_key_id`
   with **no** `user_id` — documented as a trusted internal lookup, trusting exactly
   the ownership that step 1 never established.

So a tenant who learns another tenant's key id attaches it and has the server open a
tunnel, or clone a repository, with someone else's private key.

The invariant these tests pin, deliberately phrased like the vendor-credential one it
mirrors (B1): *after any accepted write, if a connection or project carries an
`ssh_key_id`, that key belongs to the requesting user.*
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ssh_key import SshKey
from tests.integration.conftest import auth_headers, register_user


async def _plant_key(db_session: AsyncSession, owner_user_id: str) -> str:
    """Insert a key row directly.

    The API validates key material cryptographically; what is under test is the
    ownership check on the *reference*, not key parsing.
    """
    key = SshKey(
        name=f"victim-key-{uuid.uuid4().hex[:6]}",
        user_id=owner_user_id,
        private_key_encrypted="encrypted-blob",
        fingerprint=f"SHA256:{uuid.uuid4().hex}",
        key_type="ssh-ed25519",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key.id


async def _project(client: AsyncClient, headers: dict, name: str) -> str:
    resp = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _db_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "name": "attacker-conn",
        "db_type": "postgres",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
    }


class TestSshKeyOwnership:
    async def test_connection_create_cannot_reference_another_tenants_key(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_attacker = auth_headers(attacker["token"])

        victim_key = await _plant_key(db_session, victim["user_id"])
        pid = await _project(client, h_attacker, "Attacker Proj")

        payload = _db_payload(pid) | {
            "ssh_host": "10.0.0.1",
            "ssh_user": "root",
            "ssh_key_id": victim_key,
        }
        resp = await client.post("/api/connections", headers=h_attacker, json=payload)

        assert resp.status_code in (403, 404), (
            f"create accepted another tenant's ssh_key_id ({resp.status_code}): {resp.text}"
        )

    async def test_connection_patch_cannot_attach_another_tenants_key(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The PATCH variant — the shape that beat the credential check twice."""
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_attacker = auth_headers(attacker["token"])

        victim_key = await _plant_key(db_session, victim["user_id"])
        pid = await _project(client, h_attacker, "Attacker Proj")

        created = await client.post("/api/connections", headers=h_attacker, json=_db_payload(pid))
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        patched = await client.patch(
            f"/api/connections/{cid}",
            headers=h_attacker,
            json={"ssh_host": "10.0.0.1", "ssh_user": "root", "ssh_key_id": victim_key},
        )

        assert patched.status_code in (403, 404), (
            f"patch attached another tenant's ssh_key_id ({patched.status_code})"
        )

        from app.models.connection import Connection

        row = await db_session.get(Connection, cid)
        await db_session.refresh(row)
        assert row is not None
        assert row.ssh_key_id != victim_key, (
            "the attacker's connection now references the victim's SSH key"
        )

    async def test_project_update_cannot_reference_another_tenants_key(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The project path matters independently: GitAgent and the repo indexer
        both resolve `project.ssh_key_id` with no user filter."""
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_attacker = auth_headers(attacker["token"])

        victim_key = await _plant_key(db_session, victim["user_id"])
        pid = await _project(client, h_attacker, "Attacker Proj")

        resp = await client.patch(
            f"/api/projects/{pid}", headers=h_attacker, json={"ssh_key_id": victim_key}
        )

        assert resp.status_code in (403, 404), (
            f"project update accepted another tenant's ssh_key_id ({resp.status_code})"
        )

    async def test_owner_can_still_use_their_own_key(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The guard must refuse foreign keys without refusing legitimate ones."""
        owner = await register_user(client, db_session=db_session)
        h_owner = auth_headers(owner["token"])

        own_key = await _plant_key(db_session, owner["user_id"])
        pid = await _project(client, h_owner, "Owner Proj")

        resp = await client.patch(
            f"/api/projects/{pid}", headers=h_owner, json={"ssh_key_id": own_key}
        )
        assert resp.status_code == 200, resp.text

    async def test_add_repository_cannot_reference_another_tenants_key(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The fourth write site, missed by the first sweep.

        `repos.py` guards `ssh_key_id` on the *check-access* endpoint but not on
        repository creation — and the repo indexer resolves it with no owner filter.
        Grepping for a call site is not a survey of call sites.
        """
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_attacker = auth_headers(attacker["token"])

        victim_key = await _plant_key(db_session, victim["user_id"])
        pid = await _project(client, h_attacker, "Attacker Proj")

        resp = await client.post(
            f"/api/repos/{pid}/repositories",
            headers=h_attacker,
            json={
                "name": "r1",
                "repo_url": "git@github.com:someone/thing.git",
                "ssh_key_id": victim_key,
            },
        )

        assert resp.status_code in (403, 404), (
            f"add_repository accepted another tenant's ssh_key_id ({resp.status_code})"
        )
