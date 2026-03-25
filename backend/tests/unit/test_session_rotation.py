"""Tests for session rotation: summarizer, config, backup Heroku skip."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.backup_manager import BackupManager, _is_heroku
from app.llm.errors import LLMTokenLimitError


class TestSessionSummarizer:
    """Tests for the session_summarizer module."""

    @pytest.fixture
    def mock_llm_router(self):
        router = MagicMock()
        resp = MagicMock()
        resp.content = "Summary: user asked about sales data, ran queries on orders table."
        router.complete = AsyncMock(return_value=resp)
        return router

    async def test_summarize_empty_session(self, mock_llm_router):
        from app.services.session_summarizer import SessionSummary, _fallback_summary

        result = _fallback_summary([], [])
        assert result == "Previous conversation context."

    async def test_fallback_summary_with_topics(self):
        from app.services.session_summarizer import _fallback_summary

        result = _fallback_summary(["What are top sales?", "Show revenue"], ["SELECT * FROM orders"])
        assert "What are top sales?" in result
        assert "SQL queries executed: 1" in result

    async def test_fallback_summary_topics_only(self):
        from app.services.session_summarizer import _fallback_summary

        result = _fallback_summary(["revenue breakdown"], [])
        assert "revenue breakdown" in result


class TestLLMTokenLimitErrorMessage:
    """Verify the updated user_message on LLMTokenLimitError."""

    def test_user_message_is_actionable(self):
        err = LLMTokenLimitError("context limit exceeded")
        assert "fresh chat" in err.user_message.lower()
        assert "simplifying" not in err.user_message.lower()


class TestHerokuDetection:
    def test_is_heroku_true(self):
        with patch.dict("os.environ", {"DYNO": "web.1"}):
            assert _is_heroku() is True

    def test_is_heroku_false(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _is_heroku() is False


class TestBackupHerokuSkip:
    async def test_postgres_backup_skipped_on_heroku(self, tmp_path):
        mgr = BackupManager()
        mgr.backup_dir = tmp_path / "backups"
        manifest: dict = {"files": {}, "errors": []}
        dest = tmp_path / "db"

        with (
            patch("app.core.backup_manager._is_heroku", return_value=True),
            patch(
                "app.core.backup_manager.settings",
                MagicMock(database_url="postgresql+asyncpg://user:pass@host/db"),
            ),
        ):
            size = await mgr._backup_database(dest, manifest)

        assert size == 0
        assert manifest["files"]["database"]["skipped"] is True
        assert "heroku" in manifest["files"]["database"]["reason"].lower()


class TestConfigSettings:
    def test_defaults(self):
        from app.config import Settings

        s = Settings()
        assert s.session_rotation_enabled is True
        assert s.session_rotation_threshold_pct == 95
        assert s.session_rotation_summary_max_tokens == 500


class TestEstimateRotationImminent:
    """Verify the CostEstimateResponse includes rotation_imminent."""

    def test_rotation_imminent_field_exists(self):
        from app.api.routes.chat import CostEstimateResponse

        resp = CostEstimateResponse()
        assert resp.rotation_imminent is False

    def test_rotation_imminent_when_high_utilization(self):
        from app.api.routes.chat import CostEstimateResponse

        resp = CostEstimateResponse(context_utilization_pct=92.0, rotation_imminent=True)
        assert resp.rotation_imminent is True


class TestOrchestratorContextUsagePct:
    """Verify AgentResponse includes context_usage_pct field."""

    def test_context_usage_pct_default(self):
        from app.agents.orchestrator import AgentResponse

        resp = AgentResponse()
        assert resp.context_usage_pct == 0
