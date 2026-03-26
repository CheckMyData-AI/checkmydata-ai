"""Unit tests for EmailService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_service import EmailService


@pytest.fixture
def email_svc():
    return EmailService()


class TestSendWelcomeEmail:
    @pytest.mark.asyncio
    @patch("app.services.email_service.settings")
    async def test_skips_when_api_key_empty(self, mock_settings, email_svc):
        mock_settings.resend_api_key = ""
        with patch("app.services.email_service.resend") as mock_resend:
            await email_svc.send_welcome_email(
                user_id="u1", email="a@b.com", display_name="Alice"
            )
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
        send_fn = call_args[0][0]
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

        await email_svc.send_welcome_email(
            user_id="u1", email="bob@test.com", display_name=""
        )

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
    async def test_does_not_raise_on_send_failure(
        self, mock_settings, mock_to_thread, email_svc
    ):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.side_effect = Exception("API error")

        await email_svc.send_welcome_email(
            user_id="u1", email="fail@test.com", display_name="Fail"
        )

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_uses_idempotency_key(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.resend_from_email = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-100"}

        await email_svc.send_welcome_email(
            user_id="u42", email="a@b.com", display_name="A"
        )

        call_args = mock_to_thread.call_args[0]
        idempotency_opts = call_args[2]
        assert idempotency_opts == {"idempotency_key": "welcome/u42"}
