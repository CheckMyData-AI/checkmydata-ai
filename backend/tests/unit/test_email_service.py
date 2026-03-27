"""Unit tests for EmailService."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_service import EmailService


@pytest.fixture
def email_svc():
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.resend_api_key = "re_test_key"
        svc = EmailService()
    return svc


class TestSendWelcomeEmail:
    @pytest.mark.asyncio
    @patch("app.services.email_service.settings")
    async def test_skips_when_api_key_empty(self, mock_settings, email_svc):
        mock_settings.resend_api_key = ""
        with patch("app.services.email_service.resend") as mock_resend:
            await email_svc.send_welcome_email(user_id="u1", email="a@b.com", display_name="Alice")
            mock_resend.Emails.send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_sends_email_when_configured(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-123"}

        await email_svc.send_welcome_email(
            user_id="u1", email="alice@test.com", display_name="Alice"
        )

        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        params = call_args[0][1]
        assert params["to"] == ["alice@test.com"]
        assert "Welcome" in params["subject"]
        assert "Alice" in params["html"]

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_uses_email_prefix_when_no_display_name(
        self, mock_settings, mock_to_thread, email_svc
    ):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-123"}

        await email_svc.send_welcome_email(user_id="u1", email="bob@test.com", display_name="")

        params = mock_to_thread.call_args[0][1]
        assert "bob" in params["html"]


class TestSendInviteEmail:
    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_sends_invite_email(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-456"}

        await email_svc.send_invite_email(
            invite_id="inv-1",
            to_email="invited@test.com",
            project_name="My Project",
            inviter_name="Alice",
            role="editor",
        )

        mock_to_thread.assert_called_once()
        params = mock_to_thread.call_args[0][1]
        assert params["to"] == ["invited@test.com"]
        assert "My Project" in params["subject"]
        assert "Alice" in params["html"]
        assert "editor" in params["html"]


class TestSendInviteAcceptedEmail:
    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_sends_acceptance_email(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-789"}

        await email_svc.send_invite_accepted_email(
            invite_id="inv-1",
            inviter_email="owner@test.com",
            inviter_name="Owner",
            accepted_user_email="member@test.com",
            accepted_user_name="Member",
            project_name="My Project",
        )

        mock_to_thread.assert_called_once()
        params = mock_to_thread.call_args[0][1]
        assert params["to"] == ["owner@test.com"]
        assert "My Project" in params["subject"]
        assert "Member" in params["html"]


class TestErrorHandling:
    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_does_not_raise_on_send_failure(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.side_effect = Exception("API error")

        await email_svc.send_welcome_email(user_id="u1", email="fail@test.com", display_name="Fail")

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_uses_idempotency_key(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-100"}

        await email_svc.send_welcome_email(user_id="u42", email="a@b.com", display_name="A")

        call_args = mock_to_thread.call_args[0]
        options = call_args[2]
        assert options == {"idempotency_key": "welcome/u42"}


class TestHtmlEscaping:
    """User-provided values must be HTML-escaped to prevent injection."""

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_welcome_escapes_display_name(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-esc"}

        await email_svc.send_welcome_email(
            user_id="u1", email="x@y.com", display_name="<script>alert(1)</script>"
        )

        html = mock_to_thread.call_args[0][1]["html"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_invite_escapes_project_and_inviter(
        self, mock_settings, mock_to_thread, email_svc
    ):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-esc2"}

        await email_svc.send_invite_email(
            invite_id="inv-esc",
            to_email="a@b.com",
            project_name='<img src=x onerror="hack()">',
            inviter_name="<b>Evil</b>",
            role="editor",
        )

        html = mock_to_thread.call_args[0][1]["html"]
        assert "<b>Evil</b>" not in html
        assert "&lt;b&gt;Evil&lt;/b&gt;" in html
        assert 'onerror="hack()"' not in html

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_invite_accepted_escapes_all_user_values(
        self, mock_settings, mock_to_thread, email_svc
    ):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-esc3"}

        await email_svc.send_invite_accepted_email(
            invite_id="inv-esc2",
            inviter_email="safe@test.com",
            inviter_name="<em>Owner</em>",
            accepted_user_email="member@test.com",
            accepted_user_name='"><script>xss</script>',
            project_name="Safe Project",
        )

        html = mock_to_thread.call_args[0][1]["html"]
        assert "<em>Owner</em>" not in html
        assert "<script>xss</script>" not in html
        assert "&lt;script&gt;xss&lt;/script&gt;" in html


class TestRetryLogic:
    """Transient errors (429, 500) should be retried with backoff."""

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_retries_on_rate_limit_then_succeeds(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from resend.exceptions import RateLimitError

        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        rate_err = RateLimitError(
            message="Too many requests",
            error_type="rate_limit_exceeded",
            code=429,
        )
        mock_to_thread.side_effect = [rate_err, rate_err, {"id": "email-retry-ok"}]

        await email_svc.send_welcome_email(user_id="u-r", email="a@b.com", display_name="R")

        assert mock_to_thread.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_retries_on_server_error_then_succeeds(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from resend.exceptions import ApplicationError

        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        server_err = ApplicationError(
            message="Internal error",
            error_type="application_error",
            code=500,
        )
        mock_to_thread.side_effect = [server_err, {"id": "email-500-ok"}]

        await email_svc.send_welcome_email(user_id="u-s", email="a@b.com", display_name="S")

        assert mock_to_thread.call_count == 2
        assert mock_sleep.call_count == 1

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_does_not_retry_on_validation_error(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from resend.exceptions import ValidationError

        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        val_err = ValidationError(
            message="Bad request", error_type="validation_error", code=400
        )
        mock_to_thread.side_effect = val_err

        await email_svc.send_welcome_email(user_id="u-v", email="a@b.com", display_name="V")

        assert mock_to_thread.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_gives_up_after_max_retries(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from resend.exceptions import RateLimitError

        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        rate_err = RateLimitError(
            message="Too many requests",
            error_type="rate_limit_exceeded",
            code=429,
        )
        mock_to_thread.side_effect = rate_err

        await email_svc.send_welcome_email(user_id="u-max", email="a@b.com", display_name="Max")

        assert mock_to_thread.call_count == 4  # 1 initial + 3 retries
        assert mock_sleep.call_count == 3


class TestTags:
    """Emails should include category tags for Resend dashboard tracking."""

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_welcome_email_has_tags(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-tag1"}

        await email_svc.send_welcome_email(user_id="u1", email="a@b.com", display_name="A")

        params = mock_to_thread.call_args[0][1]
        assert params["tags"] == [{"name": "category", "value": "welcome"}]

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_invite_email_has_tags(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-tag2"}

        await email_svc.send_invite_email(
            invite_id="inv-t",
            to_email="a@b.com",
            project_name="P",
            inviter_name="I",
            role="editor",
        )

        params = mock_to_thread.call_args[0][1]
        assert params["tags"] == [{"name": "category", "value": "invite"}]

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_invite_accepted_email_has_tags(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-tag3"}

        await email_svc.send_invite_accepted_email(
            invite_id="inv-t2",
            inviter_email="o@t.com",
            inviter_name="O",
            accepted_user_email="m@t.com",
            accepted_user_name="M",
            project_name="P",
        )

        params = mock_to_thread.call_args[0][1]
        assert params["tags"] == [{"name": "category", "value": "invite-accepted"}]
