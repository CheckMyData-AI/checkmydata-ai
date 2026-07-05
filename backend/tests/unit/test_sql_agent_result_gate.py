"""DATA-06: single-query path runs the shared ResultValidation gate."""

from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest

from app.connectors.base import QueryResult

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("app.agents.result_validation") is None,
    reason="W0 C-B/C-C ResultValidation not merged yet — this task depends on W0.",
)


def _make_rv(fake_evaluate):
    """Build a lightweight ResultValidation stand-in with a patched evaluate."""
    return type("RV", (), {"evaluate": fake_evaluate})()


async def test_result_gate_appends_warning_on_block(monkeypatch):
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)  # bypass heavy __init__
    fake = MagicMock(  # evaluate is SYNC — a plain MagicMock, not AsyncMock
        return_value=ResultDirective(
            action="block",
            reason="Column 'conversion_pct' has value 150 out of range for a percentage.",
            hints=["Cast to ratio 0..1"],
        )
    )
    monkeypatch.setattr(sql_agent_mod, "_build_result_validation", lambda *a, **k: _make_rv(fake))

    qr = QueryResult(columns=["conversion_pct"], rows=[[150]], row_count=1)
    ctx = type("Ctx", (), {"user_question": "conversion?"})()
    text = await agent._run_result_gate(qr, "SELECT conversion_pct FROM t", ctx)
    assert "out of range" in text.lower() or "impossible" in text.lower()
    assert "150" in text


async def test_result_gate_silent_on_accept(monkeypatch):
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)
    fake = MagicMock(return_value=ResultDirective(action="accept", reason="", hints=[]))
    monkeypatch.setattr(sql_agent_mod, "_build_result_validation", lambda *a, **k: _make_rv(fake))
    qr = QueryResult(columns=["n"], rows=[[5]], row_count=1)
    ctx = type("Ctx", (), {"user_question": "count?"})()
    assert await agent._run_result_gate(qr, "SELECT COUNT(*) FROM t", ctx) == ""


async def test_result_gate_increments_datagate_block_total(monkeypatch):
    """DATA-06: _run_result_gate must NOT double-count datagate_block_total.

    The metric is incremented ONCE inside ResultValidation.evaluate — not in
    _run_result_gate.  This test verifies (a) warning text is still emitted on
    a block directive and (b) the counter does NOT change a second time inside
    _run_result_gate itself.
    """
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective
    from app.core.metrics import get_metrics_collector

    collector = get_metrics_collector()
    before = collector.snapshot_counters().get("datagate_block_total", 0)

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)
    fake = MagicMock(
        return_value=ResultDirective(
            action="block",
            reason="Column 'count' has negative value -5 which is impossible for a count/quantity.",
            hints=[],
        )
    )
    monkeypatch.setattr(
        sql_agent_mod,
        "_build_result_validation",
        lambda *a, **k: _make_rv(fake),
    )

    qr = QueryResult(columns=["count"], rows=[[-5]], row_count=1)
    ctx = type("Ctx", (), {"user_question": "how many?"})()
    text = await agent._run_result_gate(qr, "SELECT COUNT(*) FROM t", ctx)

    after = collector.snapshot_counters().get("datagate_block_total", 0)
    # The metric must NOT be incremented inside _run_result_gate (DATA-06 fix).
    # ResultValidation.evaluate is mocked here so the evaluate-side increment
    # is also skipped — counter must stay flat.
    assert after == before, (
        "datagate_block_total must NOT be incremented inside _run_result_gate "
        f"(double-count fix DATA-06); before={before}, after={after}"
    )
    assert text != "", "warning text should be non-empty on block"


async def test_result_gate_warn_appends_text(monkeypatch):
    """Warn directive still produces warning text (not empty)."""
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)
    fake = MagicMock(
        return_value=ResultDirective(
            action="warn",
            reason="PARTIAL DATA: query capped at 1000 rows.",
            hints=["Push aggregation into SQL."],
        )
    )
    monkeypatch.setattr(sql_agent_mod, "_build_result_validation", lambda *a, **k: _make_rv(fake))
    qr = QueryResult(columns=["n"], rows=[[5]], row_count=1000, truncated=True)
    ctx = type("Ctx", (), {"user_question": "how many?"})()
    text = await agent._run_result_gate(qr, "SELECT n FROM t LIMIT 1000", ctx)
    assert text != ""
    assert "partial" in text.lower() or "warn" in text.lower()
