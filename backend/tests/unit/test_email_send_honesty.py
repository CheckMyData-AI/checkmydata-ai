"""F-PROJ-06 — a failed email returned 200 and said nothing.

The board recorded this as "commit-then-await-email → partial-success 500s". Measured, the
opposite happens: `EmailService._send` catches everything, calls `logger.exception` and
returns `None`, so a send that fails never reaches the route. There is no 500. The route
answers **200 with an invite the recipient will never hear about.**

The 409 on retry then confirms the wrong conclusion. An owner who suspects nothing arrived
tries again and gets "Invite already pending for this email", which reads as *already
done* — so the invitation is recorded, undelivered, and the person who sent it believes it
worked.

That is `vision.md` §7: never tell the user something happened when it did not. The fix is
one mechanism — `_send` reports whether it sent — and a decision per call site, because the
consequences differ:

* **verification mail** — without it an account cannot verify, so the user is stuck;
* **invite mail** — the owner needs to know so they can resend or paste the link;
* **password reset** — must stay silent. That route deliberately answers a uniform
  `{"ok": True}` so the response cannot be used to probe which addresses exist, and a
  field that appears only when an account exists is exactly that oracle rebuilt.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_service import EmailService


class TestSendReportsWhetherItSent:
    async def test_a_successful_send_reports_true(self):
        with patch("app.services.email_service.resend.Emails.send", return_value={"id": "e1"}):
            with patch.object(EmailService, "_is_configured", return_value=True, create=True):
                ok = await EmailService()._send(to="a@b.c", subject="s", html="<p>b</p>")

        assert ok is True

    async def test_a_failed_send_reports_false_and_does_not_raise(self):
        """It must not raise: the row is already committed, and turning a notification
        failure into a 500 would tell the caller the whole operation failed."""
        with patch(
            "app.services.email_service.resend.Emails.send", side_effect=RuntimeError("smtp down")
        ):
            with patch.object(EmailService, "_is_configured", return_value=True, create=True):
                ok = await EmailService()._send(to="a@b.c", subject="s", html="<p>b</p>")

        assert ok is False


class TestEverySenderPropagatesIt:
    """One mechanism, six senders. A sender that swallows the result puts the decision back
    where it cannot be made."""

    @pytest.mark.parametrize(
        "name",
        [
            "send_invite_email",
            "send_verification_email",
            "send_welcome_email",
            "send_password_reset_email",
            "send_invite_accepted_email",
            "send_access_request_email",
        ],
    )
    def test_the_signature_returns_bool(self, name):
        """Compared as a string, not as a type: `email_service` uses
        `from __future__ import annotations`, so PEP 563 leaves every annotation a string
        and `is bool` is false against correct code. My first version asserted the type and
        went red against six signatures that were already right."""
        sig = inspect.signature(getattr(EmailService, name))
        annotation = sig.return_annotation

        assert annotation in (bool, "bool"), (
            f"{name} returns {annotation!r} — it discards whether the mail went out, so no "
            "caller can report it"
        )


class TestTheInviteRouteTellsTheTruth:
    """Structural first, behavioural after. The first version of this class asserted only
    that `InviteResponse` HAS an `email_sent` field, and a plant that stopped the route
    passing it left every test green — a field nothing populates is a field that reports
    nothing. Three of five plants walked past this class before these were added."""

    def test_the_field_exists(self):
        from app.api.routes.invites import InviteResponse

        assert "email_sent" in InviteResponse.model_fields

    async def test_the_create_route_passes_a_failed_send_through(self):
        import app.api.routes.invites as inv

        with patch.object(inv._email_svc, "send_invite_email", AsyncMock(return_value=False)):
            body = await _create_invite_via_route(inv)

        assert body.email_sent is False, "the owner is told the invitation was sent when it was not"

    async def test_the_create_route_reports_a_successful_send(self):
        import app.api.routes.invites as inv

        with patch.object(inv._email_svc, "send_invite_email", AsyncMock(return_value=True)):
            body = await _create_invite_via_route(inv)

        assert body.email_sent is True

    async def test_the_resend_route_reports_a_failed_send(self):
        """Resending is what somebody does *because* they suspect the first never arrived,
        so `{"ok": True}` from a resend that did not send is the worse of the two lies."""
        import app.api.routes.invites as inv

        src = inspect.getsource(inv.resend_invite)

        assert '"email_sent": email_sent' in src or "email_sent=email_sent" in src, (
            "the resend route answers ok regardless of whether anything was sent"
        )

    def test_the_duplicate_409_points_at_the_resend_route(self):
        """An owner who suspects nothing arrived retries and is told "already pending",
        which reads as already done. The message has to name the way out."""
        import app.services.invite_service as svc

        src = inspect.getsource(svc.InviteService.create_invite)

        assert "resend" in src.lower(), (
            "the 409 tells the owner the invite exists and not how to get it delivered"
        )


class TestPasswordResetStaysSilent:
    def test_the_route_does_not_report_send_status(self):
        """The one site that must NOT surface it. That route answers a uniform
        `{"ok": True}` precisely so the response cannot distinguish a real account from an
        unknown one; a field that appears only when a send was attempted rebuilds the
        oracle the docstring exists to prevent."""
        import app.api.routes.auth as auth

        src = inspect.getsource(auth.forgot_password)

        assert "email_sent" not in src
        assert "ok" in src

    def test_the_reason_is_written_at_the_site(self):
        """A silence that looks like an oversight gets 'fixed' by the next reader."""
        import app.api.routes.auth as auth

        src = inspect.getsource(auth.forgot_password)

        assert "enumerat" in src.lower() or "oracle" in src.lower()


class TestRegistrationSurfacesAStuckAccount:
    """Written against a `RegisterResponse` that does not exist — registration returns the
    shared `AuthResponse` through `_auth_response`. The claim was right and the location
    was invented, which is the cheapest kind of wrong test to write and the easiest to
    believe."""

    def test_the_auth_response_can_carry_verification_status(self):
        from app.api.routes.auth import AuthResponse

        assert "verification_email_sent" in AuthResponse.model_fields, (
            "without the verification mail the account cannot verify, and the user is left "
            "waiting for something that will never arrive"
        )

    def test_register_passes_the_send_result_through(self):
        """Checked as a call argument, not as a substring. The first version asserted
        `"verification_email_sent" in src`, which stayed true when the plant removed the
        keyword from the response call — the local assignment still mentioned it. A name
        appearing somewhere in a function says nothing about where it goes."""
        import ast
        import textwrap

        from app.api.routes import auth

        tree = ast.parse(textwrap.dedent(inspect.getsource(auth.register)))
        passed = [
            kw
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg == "verification_email_sent"
        ]

        assert passed, (
            "the register route computes whether the verification mail went out and never "
            "hands it to the response"
        )


async def _create_invite_via_route(inv):
    """Drive `create_invite` with the collaborators stubbed, so the assertion is about the
    route's own reporting rather than about membership, persistence or email plumbing."""
    from types import SimpleNamespace

    invite = SimpleNamespace(
        id="i1",
        project_id="p1",
        email="a@b.c",
        role="editor",
        status="pending",
        invited_by="u1",
        created_at=None,
        accepted_at=None,
        project=SimpleNamespace(name="Proj"),
        inviter=SimpleNamespace(display_name="Owner"),
    )
    # A real Request, minimally scoped: the route carries `@limiter.limit`, and slowapi
    # rejects anything that is not a starlette Request. Faking it would mean patching the
    # limiter, which is machinery this test has no business touching.
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/projects/p1/invites",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "app": SimpleNamespace(state=SimpleNamespace(limiter=None)),
        }
    )
    with (
        patch.object(inv._membership_svc, "require_role", AsyncMock(return_value="owner")),
        patch.object(inv._invite_svc, "create_invite", AsyncMock(return_value=invite)),
        patch.object(inv, "audit_log", lambda *a, **k: None),
    ):
        return await inv.create_invite(
            request=request,
            project_id="p1",
            body=SimpleNamespace(email="a@b.c", role="editor"),
            db=AsyncMock(),
            user={"user_id": "u1", "email": "o@b.c"},
        )
