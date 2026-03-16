"""Integration tests for /api/invites endpoints."""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email():
    return f"inv-{uuid.uuid4().hex[:8]}@test.com"


@pytest.mark.asyncio
class TestInviteRoutes:
    async def _owner_project(self, client):
        """Register a user, create a project, return (owner_info, project_id)."""
        owner = await register_user(client)
        resp = await client.post(
            "/api/projects", json={"name": "Invite Proj"},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        return owner, resp.json()["id"]

    async def test_owner_can_create_invite(self, client):
        owner, pid = await self._owner_project(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": _email(), "role": "editor"},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    async def test_owner_can_list_invites(self, client):
        owner, pid = await self._owner_project(client)
        await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": _email()},
            headers=auth_headers(owner["token"]),
        )
        resp = await client.get(
            f"/api/invites/{pid}/invites",
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_owner_can_revoke_invite(self, client):
        owner, pid = await self._owner_project(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": _email()},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]
        resp = await client.delete(
            f"/api/invites/{pid}/invites/{invite_id}",
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200

    async def test_non_owner_cannot_create_invite(self, client):
        owner, pid = await self._owner_project(client)
        viewer = await register_user(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": viewer["email"], "role": "viewer"},
            headers=auth_headers(owner["token"]),
        )
        await client.post(
            f"/api/invites/accept/{resp.json()['id']}",
            headers=auth_headers(viewer["token"]),
        )

        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": _email()},
            headers=auth_headers(viewer["token"]),
        )
        assert resp.status_code == 403

    async def test_accept_invite_creates_membership(self, client):
        owner, pid = await self._owner_project(client)
        invited = await register_user(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": invited["email"], "role": "editor"},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]

        resp = await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(invited["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"

        resp = await client.get("/api/projects", headers=auth_headers(invited["token"]))
        pids = [p["id"] for p in resp.json()]
        assert pid in pids

    async def test_pending_invites_endpoint(self, client):
        owner, pid = await self._owner_project(client)
        invited = await register_user(client)
        await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": invited["email"]},
            headers=auth_headers(owner["token"]),
        )
        resp = await client.get(
            "/api/invites/pending",
            headers=auth_headers(invited["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_members_list(self, client):
        owner, pid = await self._owner_project(client)
        resp = await client.get(
            f"/api/invites/{pid}/members",
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) >= 1
        roles = [m["role"] for m in members]
        assert "owner" in roles

    async def test_owner_can_remove_non_owner_member(self, client):
        owner, pid = await self._owner_project(client)
        member = await register_user(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": member["email"], "role": "editor"},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]
        await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(member["token"]),
        )

        resp = await client.delete(
            f"/api/invites/{pid}/members/{member['user_id']}",
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 200

    async def test_non_owner_cannot_remove_members(self, client):
        owner, pid = await self._owner_project(client)
        member = await register_user(client)
        resp = await client.post(
            f"/api/invites/{pid}/invites",
            json={"email": member["email"], "role": "editor"},
            headers=auth_headers(owner["token"]),
        )
        invite_id = resp.json()["id"]
        await client.post(
            f"/api/invites/accept/{invite_id}",
            headers=auth_headers(member["token"]),
        )

        resp = await client.delete(
            f"/api/invites/{pid}/members/{owner['user_id']}",
            headers=auth_headers(member["token"]),
        )
        assert resp.status_code == 403
