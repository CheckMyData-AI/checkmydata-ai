"""Unit tests for EmailService."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_service import EmailService


@pytest.fixture
def email_svc():
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        svc = EmailService()
    return svc


class TestSendWelcomeEmail:
    @pytest.mark.asyncio
    @patch("app.services.email_service.settings")
    async def test_skips_when_api_key_empty(self, mock_settings, email_svc):
        mock_settings.cloudflare_email_api_token = ""
        with patch("app.services.email_service._cf_send") as mock_send:
            await email_svc.send_welcome_email(user_id="u1", email="a@b.com", display_name="Alice")
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_sends_email_when_configured(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.side_effect = Exception("API error")

        await email_svc.send_welcome_email(user_id="u1", email="fail@test.com", display_name="Fail")

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_uses_idempotency_key(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
    """Only a send that cannot have gone (429, unreachable) is retried; unknown is not."""

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_retries_on_rate_limit_then_succeeds(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from app.services.email_service import EmailNotSentError

        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        rate_err = EmailNotSentError("rate limited")
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
    async def test_does_not_retry_an_unknown_outcome(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        """A 5xx may already have delivered the mail: a retry would be a second email."""
        from app.services.email_service import EmailOutcomeUnknownError

        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        mock_to_thread.side_effect = [EmailOutcomeUnknownError("answered 502"), {"id": "never"}]

        sent = await email_svc.send_welcome_email(user_id="u-s", email="a@b.com", display_name="S")

        assert sent is False
        assert mock_to_thread.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_does_not_retry_on_validation_error(
        self, mock_settings, mock_to_thread, mock_sleep, email_svc
    ):
        from app.services.email_service import EmailRefusedError

        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        val_err = EmailRefusedError("refused (400)")
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
        from app.services.email_service import EmailNotSentError

        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"

        rate_err = EmailNotSentError("rate limited")
        mock_to_thread.side_effect = rate_err

        await email_svc.send_welcome_email(user_id="u-max", email="a@b.com", display_name="Max")

        assert mock_to_thread.call_count == 4  # 1 initial + 3 retries
        assert mock_sleep.call_count == 3


class TestTags:
    """Emails keep a category tag in their params (Cloudflare takes none; kept for the log)."""

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_welcome_email_has_tags(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
        mock_settings.app_url = "https://app.test.com"
        mock_to_thread.return_value = {"id": "email-tag1"}

        await email_svc.send_welcome_email(user_id="u1", email="a@b.com", display_name="A")

        params = mock_to_thread.call_args[0][1]
        assert params["tags"] == [{"name": "category", "value": "welcome"}]

    @pytest.mark.asyncio
    @patch("app.services.email_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.email_service.settings")
    async def test_invite_email_has_tags(self, mock_settings, mock_to_thread, email_svc):
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
        mock_settings.cloudflare_email_api_token = "cf_test_token"
        mock_settings.cloudflare_email_account_id = "acct"
        mock_settings.email_from = "Test <noreply@test.com>"
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
