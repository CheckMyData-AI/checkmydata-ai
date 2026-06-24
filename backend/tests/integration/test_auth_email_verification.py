"""R4 — F-PROJ-01: email verification gates invite auto-accept; F-AUTH-15/16: durable audit."""

import logging
import uuid

import pytest
from sqlalchemy import select

import app.api.routes.auth as auth_routes
from app.models.audit_log import AuditLog
from app.models.project_member import ProjectMember
from tests.integration.conftest import auth_headers, register_user


async def _is_member(db_session, project_id: str, user_id: str) -> bool:
    rows = (
        (
            await db_session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows) > 0


@pytest.mark.asyncio
async def test_register_does_not_autoaccept_until_verified(client, db_session, monkeypatch):
    # Capture the verification token the route would email.
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(auth_routes._email_svc, "send_verification_email", _capture)

    owner = await register_user(client, db_session=db_session)
    proj = await client.post(
        "/api/projects", json={"name": "P"}, headers=auth_headers(owner["token"])
    )
    pid = proj.json()["id"]

    invitee_email = f"invitee-{uuid.uuid4().hex[:8]}@test.com"
    inv = await client.post(
        f"/api/invites/{pid}/invites",
        json={"email": invitee_email, "role": "editor"},
        headers=auth_headers(owner["token"]),
    )
    assert inv.status_code == 200, inv.text

    # Register as the invitee — must NOT auto-accept (email unverified).
    reg = await client.post(
        "/api/auth/register", json={"email": invitee_email, "password": "testpass123"}
    )
    assert reg.status_code == 200
    invitee_id = reg.json()["user"]["id"]
    assert not await _is_member(db_session, pid, invitee_id), "must not be a member before verify"
    assert captured.get("token"), "a verification token should have been emailed"

    # Verify the email → now the pending invite is auto-accepted.
    ver = await client.post("/api/auth/verify-email", json={"token": captured["token"]})
    assert ver.status_code == 200
    assert ver.json()["invites_accepted"] == 1
    assert await _is_member(db_session, pid, invitee_id), "member after verify"


@pytest.mark.asyncio
async def test_verify_email_invalid_token_rejected(client):
    resp = await client.post("/api/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_audit_log_persists_row(client, db_session, caplog):
    # Registration emits auth.register → a durable audit row should land.
    email = f"audit-{uuid.uuid4().hex[:8]}@test.com"
    with caplog.at_level(logging.INFO, logger="audit"):
        resp = await client.post(
            "/api/auth/register", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200

    # The persistence runs as a fire-and-forget task; await the scheduled tasks.
    import asyncio

    await asyncio.sleep(0.05)

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "auth.register", AuditLog.detail == email)
            )
        )
        .scalars()
        .all()
    )
    assert rows, "auth.register should be persisted to audit_logs"
