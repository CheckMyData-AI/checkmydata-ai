"""Tests for :mod:`app.agents.answer_validator`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.answer_validator import AnswerValidator, _parse_validator_output
from app.llm.errors import LLMError


def _llm_with_response(text: str) -> MagicMock:
    router = MagicMock()
    response = MagicMock()
    response.content = text
    router.complete = AsyncMock(return_value=response)
    return router


class TestParseValidatorOutput:
    def test_clean_json(self):
        result = _parse_validator_output(
            '{"addresses_question": true, "confidence": 0.9, '
            '"is_partial": false, "reason": "ok"}'
        )
        assert result.addresses_question is True
        assert result.confidence == 0.9
        assert result.is_partial is False

    def test_code_fenced_json(self):
        text = '```json\n{"addresses_question": false, "confidence": 0.8, "reason": "cut"}\n```'
        result = _parse_validator_output(text)
        assert result.addresses_question is False
        assert result.reason == "cut"

    def test_invalid_defaults_to_pass(self):
        result = _parse_validator_output("not json at all")
        assert result.addresses_question is True
        assert result.confidence == 0.0


class TestAnswerValidator:
    @pytest.mark.asyncio
    async def test_empty_answer_is_partial(self):
        validator = AnswerValidator(_llm_with_response(""))
        verdict = await validator.validate(question="q", answer="")
        assert verdict.addresses_question is False
        assert verdict.is_partial is True

    @pytest.mark.asyncio
    async def test_judges_addressed(self):
        llm = _llm_with_response(
            '{"addresses_question": true, "confidence": 0.95, "reason": "good"}'
        )
        validator = AnswerValidator(llm)
        verdict = await validator.validate(
            question="What is total revenue?",
            answer="Total revenue is $10,000.",
            sql_summaries=["select sum(amount) -> 10000"],
        )
        assert verdict.addresses_question is True
        assert verdict.confidence == 0.95
        llm.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_judges_partial(self):
        llm = _llm_with_response(
            '{"addresses_question": false, "is_partial": true, '
            '"confidence": 0.9, "reason": "ran out of steps"}'
        )
        validator = AnswerValidator(llm)
        verdict = await validator.validate(
            question="What is X?",
            answer="Analysis was cut short. Please continue.",
        )
        assert verdict.addresses_question is False
        assert verdict.is_partial is True

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_pass(self):
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=LLMError("boom"))
        validator = AnswerValidator(llm)
        verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is True
        assert verdict.confidence == 0.0
