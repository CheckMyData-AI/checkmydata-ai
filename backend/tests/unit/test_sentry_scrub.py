"""PII/secret scrubbing for Sentry events (T-OBS-1)."""

from __future__ import annotations

from unittest.mock import patch

from app.core.sentry import init_sentry, scrub_event, scrub_text


class TestScrubText:
    def test_bearer_token_redacted(self):
        out = scrub_text("failed with Authorization: Bearer abcdef1234567890")
        assert "abcdef1234567890" not in out
        assert "[redacted]" in out

    def test_api_key_assignment_redacted(self):
        out = scrub_text("request failed: api_key=sk-live-123456 retry")
        assert "sk-live-123456" not in out

    def test_password_kv_redacted(self):
        out = scrub_text("password: hunter2hunter2")
        assert "hunter2hunter2" not in out

    def test_url_credentials_redacted(self):
        out = scrub_text("connect to postgres://admin:s3cr3t@db.internal:5432/app")
        assert "s3cr3t" not in out
        assert "admin" in out  # username preserved, only password dropped

    def test_plain_text_untouched(self):
        msg = "division by zero in stage executor"
        assert scrub_text(msg) == msg


class TestScrubEvent:
    def test_request_payloads_dropped(self):
        event = {
            "request": {
                "url": "https://api.example.com/ask",
                "data": {"question": "secret business data"},
                "headers": {"Authorization": "Bearer xyz"},
                "cookies": "cmd_at=token",
                "query_string": "token=abc",
                "env": {"REMOTE_ADDR": "1.2.3.4"},
            }
        }
        out = scrub_event(event)
        req = out["request"]
        assert "data" not in req
        assert "headers" not in req
        assert "cookies" not in req
        assert "query_string" not in req
        assert "env" not in req
        assert req["url"] == "https://api.example.com/ask"

    def test_user_reduced_to_id(self):
        event = {
            "user": {"id": "u1", "email": "a@b.c", "username": "alice", "ip_address": "1.1.1.1"}
        }
        out = scrub_event(event)
        assert out["user"] == {"id": "u1"}

    def test_user_without_id_emptied(self):
        event = {"user": {"email": "a@b.c"}}
        assert scrub_event(event)["user"] == {}

    def test_exception_values_scrubbed(self):
        event = {
            "exception": {
                "values": [{"type": "RuntimeError", "value": "auth failed token=abc123def456"}]
            }
        }
        out = scrub_event(event)
        assert "abc123def456" not in out["exception"]["values"][0]["value"]

    def test_breadcrumb_data_dropped_and_message_scrubbed(self):
        event = {
            "breadcrumbs": {
                "values": [
                    {"message": "calling api_key=sk-test-999", "data": {"body": "raw"}},
                ]
            }
        }
        out = scrub_event(event)
        crumb = out["breadcrumbs"]["values"][0]
        assert "sk-test-999" not in crumb["message"]
        assert "data" not in crumb

    def test_minimal_event_passthrough(self):
        assert scrub_event({}) == {}


class TestInitSentry:
    def test_noop_without_dsn(self):
        with patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = ""
            assert init_sentry() is False

    def test_frame_local_variables_are_not_captured(self):
        """H5: frame locals hold decrypted credentials and ``before_send`` never sees them.

        The SDK defaults ``include_local_variables=True``, which attaches
        ``repr()``-ed locals under ``exception.values[].stacktrace.frames[].vars``
        — a payload :func:`scrub_event` does not walk. Any exception raised in a
        frame holding a ``ConnectionConfig`` would therefore ship the DB
        password, the SSH key or the decrypted service-account JSON to Sentry.
        """
        with patch("app.core.sentry.settings") as mock_settings, patch("sentry_sdk.init") as init:
            mock_settings.sentry_dsn = "https://public@sentry.example.com/1"
            mock_settings.sentry_environment = "test"
            mock_settings.environment = "test"
            mock_settings.sentry_traces_sample_rate = 0.0
            mock_settings.sentry_profiles_sample_rate = 0.0

            assert init_sentry() is True

        assert init.call_args.kwargs["include_local_variables"] is False
        # The rest of the privacy posture must survive alongside it.
        assert init.call_args.kwargs["send_default_pii"] is False
