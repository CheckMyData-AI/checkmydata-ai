"""Unit tests for result_validation.py (contracts C-B / C-C).

Tests cover:
- ResultDirective dataclass
- ResultValidation.evaluate() — block/requery/warn/accept paths
- AnswerQualityGate.evaluate() — async block/requery/accept paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.answer_validator import AnswerValidationResult
from app.agents.data_gate import DataGate
from app.agents.result_validation import AnswerQualityGate, ResultDirective, ResultValidation
from app.agents.validation import AgentResultValidator
from app.connectors.base import QueryResult


def _rv() -> ResultValidation:
    return ResultValidation(DataGate(), AgentResultValidator())


# ---------------------------------------------------------------------------
# ResultDirective
# ---------------------------------------------------------------------------


def test_result_directive_is_dataclass():
    d = ResultDirective(action="accept", reason="ok")
    assert d.action == "accept"
    assert d.reason == "ok"
    assert d.hints == []


def test_result_directive_hints_not_shared():
    d1 = ResultDirective(action="accept", reason="ok")
    d2 = ResultDirective(action="warn", reason="warn")
    d1.hints.append("x")
    assert d2.hints == [], "hints list must not be shared between instances"


# ---------------------------------------------------------------------------
# ResultValidation.evaluate — happy paths
# ---------------------------------------------------------------------------


def test_accept_clean_result():
    qr = QueryResult(columns=["n"], rows=[[5]], row_count=1)
    d = _rv().evaluate(qr, question="how many", sql="SELECT count(*) n FROM t")
    assert isinstance(d, ResultDirective)
    assert d.action == "accept"


def test_db_error_blocks():
    qr = QueryResult(columns=[], rows=[], row_count=0, error="syntax error")
    d = _rv().evaluate(qr, question="q", sql="SELCT 1")
    assert d.action == "block"
    assert "syntax" in d.reason


def test_truncated_warns():
    qr = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=True)
    d = _rv().evaluate(qr, question="q", sql="SELECT a FROM t")
    assert d.action == "warn"
    assert "PARTIAL DATA" in d.reason


def test_truncated_kwarg_also_warns():
    """truncated= kwarg should produce a warn even if qr.truncated is False."""
    qr = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=False)
    d = _rv().evaluate(qr, question="q", sql="SELECT a FROM t", truncated=True)
    assert d.action == "warn"
    assert "PARTIAL DATA" in d.reason


def test_empty_result_requeries_when_flag_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "query_empty_result_retry", True)
    qr = QueryResult(columns=["a"], rows=[], row_count=0)
    d = _rv().evaluate(qr, question="q", sql="SELECT a FROM t WHERE 1=0")
    assert d.action == "requery"


def test_empty_result_accepts_when_flag_off(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "query_empty_result_retry", False)
    qr = QueryResult(columns=["a"], rows=[], row_count=0)
    d = _rv().evaluate(qr, question="q", sql="SELECT a FROM t WHERE 1=0")
    assert d.action == "accept"


def test_result_gate_fail_requeries():
    """validate_sql_result fails when query is empty — shim must supply a non-empty sql."""
    # Pass empty sql to trigger the "did not produce a query" gate failure.
    qr = QueryResult(columns=["a"], rows=[[1]], row_count=1)
    d = _rv().evaluate(qr, question="q", sql="")
    assert d.action == "requery"
    # Hints should carry the gate's error message.
    assert any("query" in h.lower() for h in d.hints)


def test_custom_reconcile_accepted():
    """A custom reconcile callable must be accepted by the constructor."""
    called: list[object] = []

    def spy_reconcile(results):  # type: ignore[override]
        called.append(results)
        return True

    # Only verify the constructor accepts the callable; reconcile is designed
    # for multi-result cross-checking at the call-site and is NOT invoked
    # inside evaluate() (which processes a single QueryResult).
    rv = ResultValidation(DataGate(), AgentResultValidator(), reconcile=spy_reconcile)
    assert rv._reconcile is spy_reconcile


# ---------------------------------------------------------------------------
# AnswerQualityGate.evaluate — async paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_quality_gate_accept():
    from app.agents.answer_validator import AnswerValidator

    validator = MagicMock(spec=AnswerValidator)
    validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=True,
            confidence=0.9,
            reason="looks good",
            is_partial=False,
        )
    )
    gate = AnswerQualityGate(validator)
    d = await gate.evaluate(question="q", answer="42")
    assert d.action == "accept"


@pytest.mark.asyncio
async def test_answer_quality_gate_delegates_to_validator():
    from app.agents.answer_validator import AnswerValidator

    validator = MagicMock(spec=AnswerValidator)
    validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=False,
            confidence=0.9,
            reason="ran out of time",
            is_partial=True,
        )
    )
    gate = AnswerQualityGate(validator)
    d = await gate.evaluate(question="q", answer="I ran out of time")
    assert d.action in ("requery", "warn")
    assert "time" in d.reason.lower()


@pytest.mark.asyncio
async def test_answer_quality_gate_not_partial_warns():
    """When addresses_question=False and is_partial=False we expect 'warn' (not requery)."""
    from app.agents.answer_validator import AnswerValidator

    validator = MagicMock(spec=AnswerValidator)
    validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=False,
            confidence=0.3,
            reason="irrelevant answer",
            is_partial=False,
        )
    )
    gate = AnswerQualityGate(validator)
    d = await gate.evaluate(question="q", answer="unrelated text")
    assert d.action == "warn"


@pytest.mark.asyncio
async def test_answer_quality_gate_passes_kwargs():
    """Ensure optional kwargs are forwarded to the underlying validator."""
    from app.agents.answer_validator import AnswerValidator

    validator = MagicMock(spec=AnswerValidator)
    validator.validate = AsyncMock(
        return_value=AnswerValidationResult(
            addresses_question=True,
            confidence=1.0,
            reason="ok",
            is_partial=False,
        )
    )
    gate = AnswerQualityGate(validator)
    await gate.evaluate(
        question="q",
        answer="a",
        sql_summaries=["SELECT 1"],
        preferred_provider="anthropic",
        model="claude-3-5-haiku-latest",
    )
    validator.validate.assert_awaited_once_with(
        question="q",
        answer="a",
        sql_summaries=["SELECT 1"],
        preferred_provider="anthropic",
        model="claude-3-5-haiku-latest",
    )
