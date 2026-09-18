"""A-06: a distinct-people metric is counted per period and cannot be added across them.

`query_report` summed every metric uniformly — including `activeUsers`, which GA4 counts
as distinct users **within each period**. Thirty daily values summed is "visits by a user
on separate days", not "users this month", and the difference is every returning visitor.
The tool's own description promised "metrics are summed", so the model had no reason to
doubt the number.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.analytics_agent import REPORT_BINDINGS, AnalyticsAgent
from app.analytics.ga4.reports import GA4_REPORTS


def test_the_spec_says_which_metrics_may_be_added():
    overview = next(spec for spec in GA4_REPORTS if spec.name == "overview")
    by_name = {field.api_name: field for field in overview.metrics}

    assert by_name["activeUsers"].additive is False
    assert by_name["sessions"].additive is True
    assert by_name["newUsers"].additive is True, "a new user is counted once, on one day"


def test_the_binding_carries_them():
    binding = REPORT_BINDINGS["overview"]
    assert "active_users" in binding.non_additive_metrics
    assert "sessions" not in binding.non_additive_metrics


@pytest.mark.asyncio
class TestACrossPeriodQueryLeavesThemOut:
    def _agent(self):
        agent = AnalyticsAgent.__new__(AnalyticsAgent)
        return agent

    async def _run(self, group_by: str | None, start: str, end: str):
        agent = self._agent()
        captured: dict = {}

        async def _select(_self, session, state, binding, group_columns, s, e, limit, **kw):
            metrics = kw.get("metrics")
            captured["metrics"] = list(metrics if metrics is not None else binding.metric_columns)
            return [], False

        state = MagicMock()
        state.connection_id = "c1"
        state.catalogue = REPORT_BINDINGS
        state.windows = []
        state.gate_errors = []
        with (
            patch.object(AnalyticsAgent, "_select_rows", new=_select),
            patch.object(AnalyticsAgent, "_period_statuses", new=AsyncMock(return_value={})),
            patch.object(AnalyticsAgent, "_periods_with_rows", new=AsyncMock(return_value=set())),
            patch.object(AnalyticsAgent, "_session", new=MagicMock()),
        ):
            agent._session.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            agent._session.return_value.__aexit__ = AsyncMock(return_value=False)
            text = await AnalyticsAgent._tool_query_report(
                agent,
                state,
                {
                    "report": "overview",
                    "date_from": start,
                    "date_to": end,
                    **({"group_by": group_by} if group_by else {}),
                },
            )
        return captured["metrics"], text

    async def test_a_month_without_a_date_axis_drops_it_and_says_so(self):
        # Grouped by property: one row per property for the whole month, which is the
        # shape that forces a cross-period aggregate.
        metrics, text = await self._run("property_id", "2026-09-01", "2026-09-30")

        assert "active_users" not in metrics, "thirty daily counts summed is not a monthly count"
        assert "sessions" in metrics
        assert "active_users" in text and "cannot be added" in text

    async def test_grouped_by_date_it_is_answered(self):
        metrics, text = await self._run("date", "2026-09-01", "2026-09-30")

        assert "active_users" in metrics, "per period is exactly how this metric is read"
        assert "cannot be added" not in text

    async def test_one_period_is_not_a_sum(self):
        metrics, _text = await self._run("property_id", "2026-09-01", "2026-09-01")

        assert "active_users" in metrics


def test_the_tool_description_no_longer_promises_otherwise():
    from app.agents.analytics_agent import QUERY_REPORT_TOOL

    assert "cannot be added across periods" in QUERY_REPORT_TOOL.description


def test_the_select_honours_the_metric_list():
    source = inspect.getsource(AnalyticsAgent._select_rows)
    assert "if metrics is None else metrics" in source


def test_the_window_is_measured_in_periods_not_days():
    """Guard against a fix that keys on `start != end`: a monthly report's window may be
    one period and many days."""
    source = inspect.getsource(AnalyticsAgent._tool_query_report)
    assert "len(periods) > 1" in source
    assert "start != end" not in source
