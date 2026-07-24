"""Tests for :mod:`app.agents.answer_validator`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
            '{"addresses_question": true, "confidence": 0.9, "is_partial": false, "reason": "ok"}'
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

    # --- Parse failure honours fail-closed policy (audit: parse-fail-open half) ---

    def test_empty_output_fails_closed_when_configured(self):
        """Empty validator output under fail-closed → treated as not-addressed."""
        result = _parse_validator_output("", fail_closed=True)
        assert result.addresses_question is False
        assert result.is_partial is True
        assert result.confidence == 0.0

    def test_non_json_output_fails_closed_when_configured(self):
        """Non-JSON validator output under fail-closed → not-addressed."""
        result = _parse_validator_output("not json at all", fail_closed=True)
        assert result.addresses_question is False
        assert result.is_partial is True
        assert result.confidence == 0.0

    def test_invalid_json_fails_closed_when_configured(self):
        """Malformed JSON under fail-closed → not-addressed."""
        result = _parse_validator_output('{"addresses_question": tru', fail_closed=True)
        assert result.addresses_question is False
        assert result.is_partial is True
        assert result.confidence == 0.0

    def test_missing_required_field_fails_closed_when_configured(self):
        """Valid JSON missing addresses_question under fail-closed → not-addressed."""
        result = _parse_validator_output('{"confidence": 0.9, "reason": "x"}', fail_closed=True)
        assert result.addresses_question is False
        assert result.is_partial is True

    def test_parse_failure_stays_lenient_when_fail_open(self):
        """Guard: fail_closed=False keeps the lenient default on parse failure."""
        for bad in ("", "not json at all", '{"addresses_question": tru'):
            result = _parse_validator_output(bad, fail_closed=False)
            assert result.addresses_question is True, bad
            assert result.confidence == 0.0, bad

    def test_valid_json_still_parses_with_fail_closed(self):
        """A clear verdict is honoured even when fail_closed is requested."""
        result = _parse_validator_output(
            '{"addresses_question": true, "confidence": 0.9, "reason": "ok"}',
            fail_closed=True,
        )
        assert result.addresses_question is True
        assert result.confidence == 0.9


class TestStringVerdictParsing:
    """AQ-9: bool("false") is True — string verdicts must be parsed explicitly."""

    @pytest.mark.parametrize(
        "verdict, expected",
        [
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),
            ("0", False),
            ("true", True),
            ("True", True),
            ("yes", True),
            ("1", True),
        ],
    )
    def test_string_verdict_parsed_explicitly(self, verdict, expected):
        result = _parse_validator_output(
            f'{{"addresses_question": "{verdict}", "confidence": 0.9, "reason": "x"}}'
        )
        assert result.addresses_question is expected
        assert result.confidence == 0.9

    def test_numeric_0_1_verdicts(self):
        assert (
            _parse_validator_output('{"addresses_question": 0, "reason": "x"}').addresses_question
            is False
        )
        assert (
            _parse_validator_output('{"addresses_question": 1, "reason": "x"}').addresses_question
            is True
        )

    def test_uninterpretable_verdict_fails_closed_when_configured(self):
        """A verdict we cannot parse ("maybe", null) is unverifiable — it must
        route to the failure path, not be waved through as a pass."""
        for bad in ('"maybe"', "null", "2"):
            result = _parse_validator_output(
                f'{{"addresses_question": {bad}, "reason": "x"}}', fail_closed=True
            )
            assert result.addresses_question is False, bad
            assert result.is_partial is True, bad
            assert result.confidence == 0.0, bad

    def test_uninterpretable_verdict_stays_lenient_when_fail_open(self):
        for bad in ('"maybe"', "null"):
            result = _parse_validator_output(
                f'{{"addresses_question": {bad}, "reason": "x"}}', fail_closed=False
            )
            assert result.addresses_question is True, bad
            assert result.confidence == 0.0, bad

    def test_string_is_partial_parsed(self):
        result = _parse_validator_output(
            '{"addresses_question": false, "is_partial": "true", "reason": "cut"}'
        )
        assert result.addresses_question is False
        assert result.is_partial is True


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
    async def test_llm_failure_fails_closed_by_default(self):
        """R5-6: an unverifiable answer must not be asserted as verified."""
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=LLMError("boom"))
        validator = AnswerValidator(llm)
        with patch("app.config.settings.answer_validator_fail_closed", True):
            verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is False
        assert verdict.is_partial is True
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_llm_failure_fails_open_when_configured(self):
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=LLMError("boom"))
        validator = AnswerValidator(llm)
        with patch("app.config.settings.answer_validator_fail_closed", False):
            verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is True
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_malformed_output_fails_closed_via_validate(self):
        """A successful LLM call returning garbage must honour fail-closed too,
        mirroring the call-failure path (audit: parse-fail-open half)."""
        llm = _llm_with_response("garbage not json")
        validator = AnswerValidator(llm)
        with patch("app.config.settings.answer_validator_fail_closed", True):
            verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is False
        assert verdict.is_partial is True
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_malformed_output_stays_lenient_when_fail_open(self):
        """Guard: malformed LLM output under fail-open keeps the lenient default."""
        llm = _llm_with_response("garbage not json")
        validator = AnswerValidator(llm)
        with patch("app.config.settings.answer_validator_fail_closed", False):
            verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is True
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_non_llm_error_also_fails_closed(self):
        """A non-LLMError validator failure (timeout, unexpected) must also fail
        closed — not propagate and crash the response pipeline, nor silently
        present an unverified answer as verified."""
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=TimeoutError("validator timed out"))
        validator = AnswerValidator(llm)
        with patch("app.config.settings.answer_validator_fail_closed", True):
            verdict = await validator.validate(question="q", answer="some answer")
        assert verdict.addresses_question is False
        assert verdict.is_partial is True
        assert verdict.confidence == 0.0


class TestAnswerValidatorTruncation:
    """DATA-16: validator receives row_count/truncated and injects them into the payload."""

    @pytest.mark.asyncio
    async def test_validate_injects_truncation_into_payload(self):
        from app.llm.base import LLMResponse

        captured: dict = {}

        async def _complete(*, messages, **kwargs):
            captured["user"] = messages[-1].content
            return LLMResponse(
                content='{"addresses_question": true, "confidence": 0.9, '
                '"is_partial": false, "reason": "ok"}',
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                model="gpt-4",
                provider="openai",
            )

        llm = MagicMock()
        llm.complete = _complete
        v = AnswerValidator(llm)
        await v.validate(
            question="total revenue?",
            answer="Revenue is 123456.",
            sql_summaries=["1 row"],
            row_count=10000,
            truncated=True,
        )
        payload = captured["user"]
        assert "PARTIAL" in payload or "truncat" in payload.lower()
        assert "10000" in payload

    @pytest.mark.asyncio
    async def test_validate_row_count_only_no_truncation_flag(self):
        """row_count without truncated=True should still surface row count in payload."""
        from app.llm.base import LLMResponse

        captured: dict = {}

        async def _complete(*, messages, **kwargs):
            captured["user"] = messages[-1].content
            return LLMResponse(
                content='{"addresses_question": true, "confidence": 0.9, '
                '"is_partial": false, "reason": "ok"}',
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                model="gpt-4",
                provider="openai",
            )

        llm = MagicMock()
        llm.complete = _complete
        v = AnswerValidator(llm)
        await v.validate(
            question="total revenue?",
            answer="Revenue is 5.",
            row_count=5,
            truncated=False,
        )
        assert "5" in captured["user"]

    @pytest.mark.asyncio
    async def test_validate_no_row_count_omits_facts_section(self):
        """When row_count is None the payload should not have a spurious facts section."""
        from app.llm.base import LLMResponse

        captured: dict = {}

        async def _complete(*, messages, **kwargs):
            captured["user"] = messages[-1].content
            return LLMResponse(
                content='{"addresses_question": true, "confidence": 0.9, '
                '"is_partial": false, "reason": "ok"}',
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                model="gpt-4",
                provider="openai",
            )

        llm = MagicMock()
        llm.complete = _complete
        v = AnswerValidator(llm)
        await v.validate(
            question="q?",
            answer="some answer",
        )
        assert "Result facts" not in captured["user"]


class TestAnswerValidatorUsageSink:
    """R2 / C3 — validator must forward its UsageSink to the LLM call."""

    @pytest.mark.asyncio
    async def test_forwards_usage_sink_to_llm_call(self):
        from app.llm.usage_sink import AccumUsageSink

        llm = _llm_with_response('{"addresses_question": true, "confidence": 0.9, "reason": "ok"}')
        accum = AccumUsageSink()
        validator = AnswerValidator(llm, usage_sink=accum)
        await validator.validate(question="q", answer="some answer")

        assert llm.complete.call_args.kwargs.get("usage_sink") is accum

    @pytest.mark.asyncio
    async def test_default_usage_sink_is_none(self):
        """Back-compat: callers that omit usage_sink stay at None."""
        llm = _llm_with_response('{"addresses_question": true, "confidence": 0.9, "reason": "ok"}')
        validator = AnswerValidator(llm)
        await validator.validate(question="q", answer="some answer")

        assert llm.complete.call_args.kwargs.get("usage_sink") is None
