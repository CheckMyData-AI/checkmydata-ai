"""Security regressions on the analytics half of /api/connections + account delete.

Every test here corresponds to a hole an adversarial review actually walked
through, and each one fails against the implementation that shipped it:

* **B1 — cross-tenant credential attach.** The credential ownership check was
  gated on *both* the merged source type already being analytics *and*
  ``vendor_credential_id`` being present in this particular payload. Two PATCHes
  therefore beat it: attach the victim's credential while the row is still a
  database (falls to the non-analytics branch, which checks nothing), then flip
  ``source_type`` to ``ga4`` without naming the credential (analytics branch,
  key absent, check skipped). The result collected the victim's GA4 property
  into the attacker's project with the victim's service-account key.
  The invariant these tests pin: *after any PATCH, if the connection carries a
  ``vendor_credential_id``, that credential belongs to the requesting user.*
* **M5 — sources that can never succeed.** ``appstore``/``googleplay`` are valid
  ``source_type`` values and are dispatched by the hourly cron, but no fact
  tables exist for them, so such a connection would journal a failure every day
  until modules m1/m2 land.
* **The two role guards on the collect endpoints.** Deleting both
  ``require_role`` calls left 29 analytics tests green — nothing pinned them.
* **H2 — account deletion deadlock.** ``vendor_credentials.user_id`` is FK
  CASCADE while ``connections.vendor_credential_id`` is FK RESTRICT, and
  ``delete_account`` only deletes projects the user *owns*. An invite can grant
  ``role="owner"`` on someone else's project, so a co-owner leaves a referencing
  connection behind, the CASCADE fires into the RESTRICT and the whole delete
  aborts with an IntegrityError → 500. The account could never be deleted.

The refusal assertions are deliberately written as "the stored row never gained
the foreign credential" as well as a status check: a route that returned 403 but
committed the write would be the same bug with better manners.
"""

from __future__ import annotations

import json
from typing import Any

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.vendor_credential import VendorCredential
from app.services.membership_service import MembershipService
from tests.integration.conftest import auth_headers, register_user

GA4_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIBT9SECRETGA4\n-----END PRIVATE KEY-----\n"
GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "demo-project",
        "client_email": "collector@demo-project.iam.gserviceaccount.com",
        "private_key": GA4_PRIVATE_KEY,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

SOURCE_CONFIG: dict[str, Any] = {
    "property_ids": ["294380179"],
    "backfill_days": 3,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_project(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    resp = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_credential(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    provider: str = "ga4",
    name: str = "cred",
    secret: str = GA4_SECRET,
) -> str:
    resp = await client.post(
        "/api/vendor-credentials",
        headers=headers,
        json={"name": name, "provider": provider, "secret": secret},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _ga4_payload(project_id: str, credential_id: str | None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "name": "Marketing GA4",
        "source_type": "ga4",
        "vendor_credential_id": credential_id,
        "source_config": SOURCE_CONFIG,
        "collection_enabled": True,
        "collection_hour": 4,
    }
    payload.update(overrides)
    return payload


def _db_payload(project_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "name": "attacker-pg",
        "db_type": "postgres",
        "db_host": "127.0.0.1",
        "db_port": 5432,
        "db_name": "app",
        "db_user": "app",
    }
    payload.update(overrides)
    return payload


async def _reread(db_session: AsyncSession, connection_id: str) -> Connection | None:
    """Re-read a connection from the DB, ignoring anything the session cached.

    The integration ``db_session`` fixture *is* the session the app used, so a
    plain ``get`` can hand back the pre-request identity-map object and hide a
    write (or a rollback).
    """
    db_session.expire_all()
    return await db_session.get(Connection, connection_id)


async def _connection_count(db_session: AsyncSession, project_id: str) -> int:
    db_session.expire_all()
    result = await db_session.execute(
        select(func.count()).select_from(Connection).where(Connection.project_id == project_id)
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# B1 — cross-tenant credential attach via PATCH
# ---------------------------------------------------------------------------


class TestCredentialOwnershipInvariantOnPatch:
    async def test_two_step_patch_cannot_attach_another_tenants_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The confirmed exploit: database PATCH first, source_type flip second."""
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_victim = auth_headers(victim["token"])
        h_attacker = auth_headers(attacker["token"])

        victim_cred = await _create_credential(client, h_victim, name="victim-ga4")
        attacker_pid = await _create_project(client, h_attacker, "Attacker Proj")

        # Precondition: the credential exists and really is the victim's, so a
        # refusal below cannot pass for the wrong reason.
        cred_row = await db_session.get(VendorCredential, victim_cred)
        assert cred_row is not None and cred_row.user_id == victim["user_id"]

        created = await client.post(
            "/api/connections", headers=h_attacker, json=_db_payload(attacker_pid)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        # Step 2 — attach the victim's credential while the row is still a
        # database, so the merged source type is not analytics.
        step2 = await client.patch(
            f"/api/connections/{cid}",
            headers=h_attacker,
            json={"vendor_credential_id": victim_cred},
        )
        # Step 3 — become an analytics source without naming the credential.
        step3 = await client.patch(
            f"/api/connections/{cid}",
            headers=h_attacker,
            json={"source_type": "ga4", "source_config": SOURCE_CONFIG},
        )

        row = await _reread(db_session, cid)
        assert row is not None
        assert row.vendor_credential_id != victim_cred, (
            "the attacker's connection now references the victim's vendor credential"
        )
        assert row.vendor_credential_id is None
        assert {step2.status_code, step3.status_code} & {403, 404}, (
            f"neither step was refused: step2={step2.status_code} step3={step3.status_code}"
        )
        assert step2.status_code != 500 and step3.status_code != 500

    async def test_one_step_patch_with_a_foreign_credential_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The direct variant — source_type and credential in the same payload."""
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_victim = auth_headers(victim["token"])
        h_attacker = auth_headers(attacker["token"])

        victim_cred = await _create_credential(client, h_victim, name="victim-ga4-2")
        attacker_pid = await _create_project(client, h_attacker, "Attacker Proj 2")
        created = await client.post(
            "/api/connections", headers=h_attacker, json=_db_payload(attacker_pid)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}",
            headers=h_attacker,
            json={
                "source_type": "ga4",
                "vendor_credential_id": victim_cred,
                "source_config": SOURCE_CONFIG,
            },
        )
        assert resp.status_code in (403, 404), resp.text

        row = await _reread(db_session, cid)
        assert row is not None and row.vendor_credential_id is None

    async def test_foreign_credential_on_a_database_row_is_refused_on_its_own(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 2 in isolation: a database connection may not hold a vendor key."""
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        victim_cred = await _create_credential(
            client, auth_headers(victim["token"]), name="victim-ga4-3"
        )
        h_attacker = auth_headers(attacker["token"])
        pid = await _create_project(client, h_attacker, "Attacker Proj 3")
        created = await client.post("/api/connections", headers=h_attacker, json=_db_payload(pid))
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}",
            headers=h_attacker,
            json={"vendor_credential_id": victim_cred},
        )
        assert resp.status_code in (403, 404), resp.text

        row = await _reread(db_session, cid)
        assert row is not None and row.vendor_credential_id is None

    async def test_patching_an_unrelated_field_revalidates_the_stored_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The invariant is about the merged row, not about this payload's keys.

        A row that already references a foreign credential (whatever put it
        there — a pre-fix deploy, a restored backup) must not be usable by a
        PATCH that never mentions the credential.
        """
        victim = await register_user(client, db_session=db_session)
        attacker = await register_user(client, db_session=db_session)
        h_victim = auth_headers(victim["token"])
        h_attacker = auth_headers(attacker["token"])

        victim_cred = await _create_credential(client, h_victim, name="victim-ga4-4")
        attacker_pid = await _create_project(client, h_attacker, "Attacker Proj 4")
        own_cred = await _create_credential(client, h_attacker, name="attacker-ga4")
        created = await client.post(
            "/api/connections", headers=h_attacker, json=_ga4_payload(attacker_pid, own_cred)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        # Plant the foreign reference directly, bypassing the API entirely.
        row = await _reread(db_session, cid)
        assert row is not None
        row.vendor_credential_id = victim_cred
        await db_session.commit()

        resp = await client.patch(
            f"/api/connections/{cid}", headers=h_attacker, json={"collection_hour": 5}
        )
        assert resp.status_code in (403, 404), resp.text

        after = await _reread(db_session, cid)
        assert after is not None
        assert after.collection_hour == 4, "the edit was applied despite the refusal"

    async def test_owner_can_still_attach_their_own_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The regression half: the legitimate flow must be untouched."""
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "Own Proj")
        cred = await _create_credential(client, headers, name="own-ga4")
        created = await client.post("/api/connections", headers=headers, json=_db_payload(pid))
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}",
            headers=headers,
            json={
                "source_type": "ga4",
                "vendor_credential_id": cred,
                "source_config": SOURCE_CONFIG,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["vendor_credential_id"] == cred

        row = await _reread(db_session, cid)
        assert row is not None and row.vendor_credential_id == cred

    async def test_owner_can_patch_unrelated_fields_without_resending_the_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "Own Proj 2")
        cred = await _create_credential(client, headers, name="own-ga4-2")
        created = await client.post(
            "/api/connections", headers=headers, json=_ga4_payload(pid, cred)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}",
            headers=headers,
            json={"name": "Renamed GA4", "collection_hour": 9, "collection_enabled": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Renamed GA4"
        assert body["collection_hour"] == 9
        assert body["collection_enabled"] is False
        assert body["vendor_credential_id"] == cred


# ---------------------------------------------------------------------------
# M5 — vendors with no collector must not be creatable
# ---------------------------------------------------------------------------


class TestUnimplementedAnalyticsSources:
    async def test_appstore_connection_creation_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "ASC Proj")
        cred = await _create_credential(
            client, headers, provider="appstore", name="p8", secret="-----BEGIN PRIVATE KEY--"
        )

        resp = await client.post(
            "/api/connections",
            headers=headers,
            json=_ga4_payload(pid, cred, source_type="appstore", name="ASC"),
        )
        assert resp.status_code == 422, resp.text
        assert "not available yet" in resp.text
        assert await _connection_count(db_session, pid) == 0

    async def test_googleplay_connection_creation_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "Play Proj")
        cred = await _create_credential(
            client, headers, provider="googleplay", name="play-sa", secret="{}"
        )

        resp = await client.post(
            "/api/connections",
            headers=headers,
            json=_ga4_payload(pid, cred, source_type="googleplay", name="Play"),
        )
        assert resp.status_code == 422, resp.text
        assert "not available yet" in resp.text
        assert await _connection_count(db_session, pid) == 0

    async def test_ga4_connection_creation_still_works(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "GA4 Still Works")
        cred = await _create_credential(client, headers, name="ga4-ok")

        resp = await client.post("/api/connections", headers=headers, json=_ga4_payload(pid, cred))
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_type"] == "ga4"

    async def test_patch_cannot_turn_a_connection_into_an_unimplemented_source(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "Flip Proj")
        cred = await _create_credential(client, headers, name="ga4-flip")
        created = await client.post(
            "/api/connections", headers=headers, json=_ga4_payload(pid, cred)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}", headers=headers, json={"source_type": "appstore"}
        )
        assert resp.status_code == 422, resp.text
        assert "not available yet" in resp.text

        row = await _reread(db_session, cid)
        assert row is not None and row.source_type == "ga4"


# ---------------------------------------------------------------------------
# Role guards on the collect endpoints
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def shared_ga4(client: AsyncClient, db_session: AsyncSession):
    """A GA4 connection plus a viewer member and an outsider on the same project."""
    owner = await register_user(client, db_session=db_session)
    viewer = await register_user(client, db_session=db_session)
    outsider = await register_user(client, db_session=db_session)
    headers = auth_headers(owner["token"])

    pid = await _create_project(client, headers, "Guarded Proj")
    cred = await _create_credential(client, headers, name="guarded-ga4")
    created = await client.post("/api/connections", headers=headers, json=_ga4_payload(pid, cred))
    assert created.status_code == 200, created.text

    await MembershipService().add_member(db_session, pid, viewer["user_id"], role="viewer")

    yield {
        "connection_id": created.json()["id"],
        "owner": headers,
        "viewer": auth_headers(viewer["token"]),
        "outsider": auth_headers(outsider["token"]),
    }


class TestCollectEndpointRoleGuards:
    async def test_collect_refuses_a_viewer(self, client: AsyncClient, shared_ga4):
        resp = await client.post(
            f"/api/connections/{shared_ga4['connection_id']}/collect",
            headers=shared_ga4["viewer"],
        )
        assert resp.status_code == 403, resp.text

    async def test_collect_refuses_a_non_member(self, client: AsyncClient, shared_ga4):
        resp = await client.post(
            f"/api/connections/{shared_ga4['connection_id']}/collect",
            headers=shared_ga4["outsider"],
        )
        assert resp.status_code == 403, resp.text

    async def test_collection_status_refuses_a_non_member(self, client: AsyncClient, shared_ga4):
        resp = await client.get(
            f"/api/connections/{shared_ga4['connection_id']}/collection-status",
            headers=shared_ga4["outsider"],
        )
        assert resp.status_code == 403, resp.text

    async def test_collection_status_still_allows_a_viewer(self, client: AsyncClient, shared_ga4):
        """The regression half — read access is deliberately viewer-level."""
        resp = await client.get(
            f"/api/connections/{shared_ga4['connection_id']}/collection-status",
            headers=shared_ga4["viewer"],
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# H2 — account deletion must never deadlock on a co-owned project
# ---------------------------------------------------------------------------


class TestAccountDeletionWithVendorCredentials:
    async def test_co_owner_holding_a_ga4_connection_can_delete_their_account(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        host = await register_user(client, db_session=db_session)
        guest = await register_user(client, db_session=db_session)
        h_host = auth_headers(host["token"])
        h_guest = auth_headers(guest["token"])

        pid = await _create_project(client, h_host, "Co-owned Proj")
        # An invite can grant role="owner" on someone else's project.
        await MembershipService().add_member(db_session, pid, guest["user_id"], role="owner")

        cred = await _create_credential(client, h_guest, name="guest-ga4")
        created = await client.post(
            "/api/connections", headers=h_guest, json=_ga4_payload(pid, cred)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.delete("/api/auth/account", headers=h_guest)
        assert resp.status_code == 200, resp.text

        # The project belongs to the host, so its connection must survive — but
        # detached from the deleted user's credential and no longer collecting.
        row = await _reread(db_session, cid)
        assert row is not None, "the host's connection was deleted with the guest's account"
        assert row.vendor_credential_id is None
        assert row.collection_enabled is False
        assert await db_session.get(VendorCredential, cred) is None

    async def test_orphaned_analytics_connection_fails_honestly(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A credential-less GA4 source must say so, not raise something opaque."""
        from app.services.connection_service import ConnectionService

        host = await register_user(client, db_session=db_session)
        guest = await register_user(client, db_session=db_session)
        h_host = auth_headers(host["token"])
        h_guest = auth_headers(guest["token"])

        pid = await _create_project(client, h_host, "Co-owned Proj 2")
        await MembershipService().add_member(db_session, pid, guest["user_id"], role="owner")
        cred = await _create_credential(client, h_guest, name="guest-ga4-2")
        created = await client.post(
            "/api/connections", headers=h_guest, json=_ga4_payload(pid, cred)
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        assert (await client.delete("/api/auth/account", headers=h_guest)).status_code == 200

        db_session.expire_all()
        result = await ConnectionService().test_connection(db_session, cid)
        assert result["success"] is False
        assert "credential" in result["error"].lower()

    async def test_account_delete_still_works_without_any_vendor_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Regression: the plain path (own project, database connection) is unchanged."""
        owner = await register_user(client, db_session=db_session)
        headers = auth_headers(owner["token"])
        pid = await _create_project(client, headers, "Plain Proj")
        created = await client.post("/api/connections", headers=headers, json=_db_payload(pid))
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.delete("/api/auth/account", headers=headers)
        assert resp.status_code == 200, resp.text

        assert await _reread(db_session, cid) is None
