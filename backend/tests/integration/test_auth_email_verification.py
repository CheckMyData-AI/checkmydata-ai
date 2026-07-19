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
async def test_email_verified_exposed_in_register_and_me(client, db_session):
    """email_verified must be surfaced in the register response and /me (SCN-012)."""
    email = f"ev-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/auth/register", json={"email": email, "password": "testpass123"})
    assert reg.status_code == 200, reg.text
    assert reg.json()["user"]["email_verified"] is False, "fresh email account starts unverified"

    token = reg.json()["token"]
    me = await client.get("/api/auth/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    assert me.json()["email_verified"] is False


@pytest.mark.asyncio
async def test_resend_verification_sends_email_for_unverified(client, monkeypatch):
    """Resend re-issues a token and sends the verification email for an unverified user."""
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    # Swallow the registration-time send so only the resend send is captured.
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(auth_routes._email_svc, "send_verification_email", _noop)
    email = f"resend-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/auth/register", json={"email": email, "password": "testpass123"})
    assert reg.status_code == 200
    token = reg.json()["token"]

    monkeypatch.setattr(auth_routes._email_svc, "send_verification_email", _capture)
    resp = await client.post("/api/auth/resend-verification", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["already_verified"] is False
    assert captured.get("token"), "a fresh verification token should have been emailed"
    assert captured.get("email") == email


@pytest.mark.asyncio
async def test_resend_verification_noop_when_already_verified(client, monkeypatch):
    """Once verified, resend is a no-op that neither mints a token nor sends mail."""
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(auth_routes._email_svc, "send_verification_email", _capture)
    email = f"verified-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/auth/register", json={"email": email, "password": "testpass123"})
    assert reg.status_code == 200
    token = reg.json()["token"]

    # Verify first via the emailed token.
    ver = await client.post("/api/auth/verify-email", json={"token": captured["token"]})
    assert ver.status_code == 200

    captured.clear()
    resp = await client.post("/api/auth/resend-verification", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "already_verified": True}
    assert captured == {}, "no verification email should be sent for an already-verified user"


@pytest.mark.asyncio
async def test_resend_verification_noop_for_google_user(client, db_session, monkeypatch):
    """Google accounts are pre-verified; resend is a no-op and sends no email."""
    from sqlalchemy import update

    from app.models.user import User

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(auth_routes._email_svc, "send_verification_email", _capture)
    email = f"google-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/auth/register", json={"email": email, "password": "testpass123"})
    assert reg.status_code == 200
    user_id = reg.json()["user"]["id"]
    token = reg.json()["token"]

    # Simulate a Google-provisioned account (pre-verified, no password).
    await db_session.execute(
        update(User)
        .where(User.id == user_id)
        .values(auth_provider="google", email_verified=True, email_verify_token=None)
    )
    await db_session.commit()

    captured.clear()
    resp = await client.post("/api/auth/resend-verification", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "already_verified": True}
    assert captured == {}, "no verification email should be sent for a Google account"


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
