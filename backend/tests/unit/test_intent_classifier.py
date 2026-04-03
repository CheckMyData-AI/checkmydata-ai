"""Tests for the LLM-based intent classifier."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.intent_classifier import (
    IntentType,
    _extract_json,
    _extract_plain_text_intent,
    _parse_classification_response,
    _valid_intents,
    classify_intent,
)
from app.llm.base import LLMResponse, Message

# ------------------------------------------------------------------
# _valid_intents
# ------------------------------------------------------------------


class TestValidIntents:
    def test_no_capabilities(self):
        valid = _valid_intents(
            has_connection=False, has_knowledge_base=False, has_mcp_sources=False
        )
        assert valid == {"direct_response", "mixed"}

    def test_all_capabilities(self):
        valid = _valid_intents(has_connection=True, has_knowledge_base=True, has_mcp_sources=True)
        assert valid == {"direct_response", "data_query", "knowledge_query", "mcp_query", "mixed"}

    def test_db_only(self):
        valid = _valid_intents(has_connection=True, has_knowledge_base=False, has_mcp_sources=False)
        assert "data_query" in valid
        assert "knowledge_query" not in valid
        assert "mcp_query" not in valid

    def test_kb_only(self):
        valid = _valid_intents(has_connection=False, has_knowledge_base=True, has_mcp_sources=False)
        assert "knowledge_query" in valid
        assert "data_query" not in valid

    def test_mcp_only(self):
        valid = _valid_intents(has_connection=False, has_knowledge_base=False, has_mcp_sources=True)
        assert "mcp_query" in valid
        assert "data_query" not in valid


# ------------------------------------------------------------------
# _parse_classification_response
# ------------------------------------------------------------------


class TestParseClassificationResponse:
    def test_valid_json_direct_response(self):
        raw = '{"intent": "direct_response", "reason": "greeting"}'
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DIRECT_RESPONSE
        assert result.reason == "greeting"

    def test_valid_json_data_query(self):
        raw = '{"intent": "data_query", "reason": "user asks for statistics"}'
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DATA_QUERY

    def test_valid_json_knowledge_query(self):
        raw = '{"intent": "knowledge_query", "reason": "about code structure"}'
        valid = {"direct_response", "knowledge_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.KNOWLEDGE_QUERY

    def test_valid_json_mcp_query(self):
        raw = '{"intent": "mcp_query", "reason": "external data needed"}'
        valid = {"direct_response", "mcp_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MCP_QUERY

    def test_valid_json_mixed(self):
        raw = '{"intent": "mixed", "reason": "ambiguous"}'
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MIXED

    def test_invalid_intent_falls_back_to_mixed(self):
        raw = '{"intent": "data_query", "reason": "needs data"}'
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MIXED
        assert "invalid_intent" in result.reason

    def test_non_json_falls_back_to_mixed(self):
        raw = "This is just plain text, not JSON"
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MIXED
        assert result.reason == "parse_error"

    def test_json_with_code_fence(self):
        raw = '```json\n{"intent": "direct_response", "reason": "hello"}\n```'
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DIRECT_RESPONSE

    def test_json_with_prefix_text(self):
        raw = 'Here is the classification: {"intent": "data_query", "reason": "db query"}'
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DATA_QUERY

    def test_empty_string_falls_back_to_mixed(self):
        result = _parse_classification_response("", {"direct_response", "mixed"})
        assert result.intent == IntentType.MIXED

    def test_unknown_intent_value(self):
        raw = '{"intent": "totally_unknown", "reason": "test"}'
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MIXED

    def test_json_with_trailing_text(self):
        raw = '{"intent": "data_query", "reason": "needs data"} Hope this helps!'
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DATA_QUERY

    def test_plain_text_intent_recovery(self):
        raw = "data_query"
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DATA_QUERY
        assert result.reason == "recovered_from_text"

    def test_plain_text_intent_in_sentence(self):
        raw = "The intent is data_query because the user asked for statistics."
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DATA_QUERY
        assert result.reason == "recovered_from_text"

    def test_plain_text_quoted_intent(self):
        raw = '"direct_response"'
        valid = {"direct_response", "data_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.DIRECT_RESPONSE

    def test_json_embedded_in_markdown(self):
        raw = (
            "Sure! Here is the result:\n```json\n"
            '{"intent": "knowledge_query", "reason": "code Q"}\n```\n'
        )
        valid = {"direct_response", "knowledge_query", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.KNOWLEDGE_QUERY

    def test_plain_text_invalid_intent_not_in_valid(self):
        raw = "knowledge_query"
        valid = {"direct_response", "mixed"}
        result = _parse_classification_response(raw, valid)
        assert result.intent == IntentType.MIXED
        assert result.reason == "parse_error"


# ------------------------------------------------------------------
# _extract_json
# ------------------------------------------------------------------


class TestExtractJson:
    def test_clean_json(self):
        assert _extract_json('{"intent": "data_query"}') == {"intent": "data_query"}

    def test_json_with_trailing(self):
        result = _extract_json('{"intent": "data_query"} extra text')
        assert result == {"intent": "data_query"}

    def test_prefix_and_json(self):
        result = _extract_json('Result: {"intent": "mixed", "reason": "ambiguous"}')
        assert result is not None
        assert result["intent"] == "mixed"

    def test_no_json(self):
        assert _extract_json("just plain text") is None

    def test_empty(self):
        assert _extract_json("") is None

    def test_code_fence_wrapped(self):
        raw = '```json\n{"intent": "data_query"}\n```'
        result = _extract_json(raw)
        assert result == {"intent": "data_query"}


class TestExtractPlainTextIntent:
    def test_exact_match(self):
        assert _extract_plain_text_intent("data_query", {"data_query", "mixed"}) == "data_query"

    def test_quoted(self):
        result = _extract_plain_text_intent('"direct_response"', {"direct_response"})
        assert result == "direct_response"

    def test_in_sentence(self):
        result = _extract_plain_text_intent("I think this is a data_query", {"data_query", "mixed"})
        assert result == "data_query"

    def test_not_in_valid_set(self):
        assert _extract_plain_text_intent("data_query", {"direct_response", "mixed"}) is None

    def test_no_intent_found(self):
        assert _extract_plain_text_intent("hello world", {"data_query", "mixed"}) is None


# ------------------------------------------------------------------
# classify_intent (integration with mocked LLM)
# ------------------------------------------------------------------


class TestClassifyIntent:
    @pytest.fixture
    def mock_llm_router(self):
        router = MagicMock()
        router.complete = AsyncMock()
        return router

    @pytest.mark.asyncio
    async def test_classify_direct_response(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "direct_response", "reason": "greeting"}',
        )
        result = await classify_intent(
            "Hello, how are you?",
            mock_llm_router,
            has_connection=True,
            has_knowledge_base=True,
        )
        assert result.intent == IntentType.DIRECT_RESPONSE
        mock_llm_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_classify_data_query(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "data_query", "reason": "user wants stats"}',
        )
        result = await classify_intent(
            "How many users registered this month?",
            mock_llm_router,
            has_connection=True,
        )
        assert result.intent == IntentType.DATA_QUERY

    @pytest.mark.asyncio
    async def test_classify_knowledge_query(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "knowledge_query", "reason": "about models"}',
        )
        result = await classify_intent(
            "What does the User model look like?",
            mock_llm_router,
            has_knowledge_base=True,
        )
        assert result.intent == IntentType.KNOWLEDGE_QUERY

    @pytest.mark.asyncio
    async def test_classify_mcp_query(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "mcp_query", "reason": "external data"}',
        )
        result = await classify_intent(
            "Query the external analytics source",
            mock_llm_router,
            has_mcp_sources=True,
        )
        assert result.intent == IntentType.MCP_QUERY

    @pytest.mark.asyncio
    async def test_fallback_to_mixed_on_llm_error(self, mock_llm_router):
        mock_llm_router.complete.side_effect = RuntimeError("LLM is down")
        result = await classify_intent(
            "Whatever question",
            mock_llm_router,
            has_connection=True,
        )
        assert result.intent == IntentType.MIXED
        assert result.reason == "classification_error"

    @pytest.mark.asyncio
    async def test_unavailable_intent_remapped_to_mixed(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "data_query", "reason": "needs db"}',
        )
        result = await classify_intent(
            "Some question",
            mock_llm_router,
            has_connection=False,
            has_knowledge_base=True,
        )
        assert result.intent == IntentType.MIXED

    @pytest.mark.asyncio
    async def test_chat_history_included(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "direct_response", "reason": "follow-up"}',
        )
        history = [
            Message(role="user", content="Previous question"),
            Message(role="assistant", content="Previous answer"),
        ]
        result = await classify_intent(
            "Thanks!",
            mock_llm_router,
            has_connection=True,
            chat_history=history,
        )
        assert result.intent == IntentType.DIRECT_RESPONSE
        call_args = mock_llm_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        assert len(messages) >= 4  # system + 2 history + user

    @pytest.mark.asyncio
    async def test_long_question_truncated(self, mock_llm_router):
        mock_llm_router.complete.return_value = LLMResponse(
            content='{"intent": "mixed", "reason": "long question"}',
        )
        long_question = "x" * 1000
        await classify_intent(long_question, mock_llm_router)
        call_args = mock_llm_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        user_msg = [m for m in messages if m.role == "user"][0]
        assert len(user_msg.content) <= 500
