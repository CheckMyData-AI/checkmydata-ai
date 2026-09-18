"""A quiet day was called a truncation, and a figure with no window shipped bare.

P1 row 12, the answer half; ANA-01 and ANA-07.

**ANA-01** — the journal's ``error`` column carries two different meanings and
nothing distinguished them. The collect service writes the *vendor's* degraded
sentence there on an ``ok`` row (a real truncation), and it also writes the
``AnalyticsEmpty`` text there on an ``empty`` row (a correct, quiet day). Every
reader keyed the truncation caveat on ``status in DONE_STATUSES and error``, and
``empty`` is in ``DONE_STATUSES`` — so a day GA4 genuinely had nothing for was
reported to the model and to the user as *"the vendor truncated this period …
the values below are real, but lower than the true total"*, and the connection
health panel rendered the same string amber on a perfectly healthy connection.

**ANA-07** — ``has_grounding`` is satisfied by ``list_reports()`` or
``coverage()``, neither of which returns a measurement. With no window open,
``_partial_caveats`` is empty, ``_freshness_lines`` short-circuits,
``pending_periods`` is empty and the validator's only numeric warning is keyed on
``pending`` — so an invented figure shipped with no caveat, no freshness line and
no warning, past every gate the module exists to be.

The refusal is deliberately *not* the fix: both catalogue tools have legitimate
numeric answers (period counts), so refusing every figure without a window would
refuse correct answers. What was missing is the sentence saying which kind of
number this is.
"""

from __future__ import annotations

import pytest


class TestAQuietDayIsNotATruncation:
    """ANA-01."""

    def test_the_agent_does_not_call_an_empty_period_degraded(self) -> None:
        from app.agents.analytics_agent import _degraded_periods

        statuses = {
            "2026-09-01": ("ok", "GA4 report 'geo' exceeded the 10,000-row fetch cap"),
            "2026-09-02": ("empty", "GA4 returned no rows for report 'overview'"),
            "2026-09-03": ("ok", None),
        }
        degraded = _degraded_periods(list(statuses), statuses)

        assert not any(p.startswith("2026-09-02") for p in degraded), (
            "a period the vendor had nothing for is reported as 'the vendor truncated "
            "this period … the values below are real, but lower than the true total'. "
            "Nothing was truncated and the totals are complete (ANA-01)"
        )
        assert any(p.startswith("2026-09-01") for p in degraded), (
            "the real truncation must still be caveated — the writer's sentence on an "
            "ok row is the only signal the window was short"
        )

    def test_a_still_settling_period_is_not_a_truncation_either(self) -> None:
        """PRJ-10/A-04: the same column now carries a third meaning, and it is marked.

        The refetch tail is re-collected every run *because* the vendor revises it, so
        those periods carry a note. Read as a truncation it would say the numbers are a
        LOWER BOUND, which is false: they are complete as far as the vendor knows today
        and may simply be different tomorrow. The prefix is the contract, so the split
        is a lookup rather than a reading of prose.
        """
        from app.agents.analytics_agent import (
            PROVISIONAL_NOTE_PREFIX,
            _degraded_periods,
            _provisional_periods,
        )

        statuses = {
            "2026-09-01": ("ok", "GA4 report 'geo' exceeded the 10,000-row fetch cap"),
            "2026-09-02": ("ok", f"{PROVISIONAL_NOTE_PREFIX} the vendor still revises it"),
            "2026-09-03": ("ok", None),
        }
        periods = list(statuses)

        degraded = _degraded_periods(periods, statuses)
        provisional = _provisional_periods(periods, statuses)

        assert [p.split(":")[0] for p in degraded] == ["2026-09-01"]
        assert [p.split(":")[0] for p in provisional] == ["2026-09-02"]
        assert "provisional:" not in provisional[0], "the marker is plumbing, not prose"

    def test_the_two_caveats_read_differently_in_the_header(self) -> None:
        """A user told 'lower bound' acts differently from one told 'may change'."""
        from app.agents.analytics_agent import AnalyticsAgent, _Window

        header = AnalyticsAgent()._window_coverage_lines(
            _Window(
                report="overview",
                start="2026-09-01",
                end="2026-09-03",
                missing=[],
                failed=[],
                last_error=None,
                degraded=[],
                provisional=["2026-09-03: the vendor still revises this period"],
            ),
            ["2026-09-01", "2026-09-02", "2026-09-03"],
        )
        text = "\n".join(header)

        assert "STILL SETTLING" in text
        assert "may change" in text
        assert "lower than the true total" not in text, (
            "nothing was truncated; saying so sends the reader to the wrong cause"
        )
        # Every period IS collected and IS counted, so the coverage sentence stands.
        assert "real measurements" in text

    def test_the_connection_panel_does_not_show_a_caveat_for_a_quiet_day(self) -> None:
        from app.services.connection_service import _report_status

        class _Row:
            def __init__(self, period: str, status: str, error: str | None) -> None:
                self.period = period
                self.status = status
                self.error = error
                self.fetched_at = None
                self.rows_written = 0

        payload = _report_status(
            report="overview",
            grain="daily",
            entries=[_Row("2026-09-02", "empty", "GA4 returned no rows")],
            expected=["2026-09-02"],
        )

        assert payload["caveat"] is None, (
            "ConnectionHealth renders this amber as `Caveat: …` on a connection whose "
            "collection is entirely correct — the exact confusion the runbook's "
            "'if you render a caveat as an error, a successful collection looks broken' "
            "was written to prevent, one column over (ANA-01)"
        )


class TestAFigureWithNoWindowSaysSo:
    """ANA-07."""

    @pytest.mark.asyncio
    async def test_a_number_after_only_the_catalogue_carries_a_caveat(self) -> None:
        from app.agents.analytics_agent import AnalyticsAgent, _RunState

        agent = AnalyticsAgent.__new__(AnalyticsAgent)
        agent._answer_quality_note = _none  # type: ignore[method-assign]
        agent._freshness_lines = _empty  # type: ignore[method-assign]

        state = _RunState(connection_id="c1", source_name="ga4-prod", catalogue={})
        state.catalogue_reads = 1

        result = await agent._finalise(
            state,
            _NO_CONTEXT,  # `_finalise` reaches it only through the stubbed gate
            raw_answer="July had roughly 12,400 sessions, up about 8% on June.",
            token_usage={},
        )

        assert any("NO REPORT DATA" in c for c in result.caveats), (
            "the only tools called were catalogue tools, which return report names, "
            "grains and period counts — not measurements. The figure went out with "
            f"no caveat, no freshness line and no warning. Caveats: {result.caveats} "
            "(ANA-07)"
        )
        assert "NO REPORT DATA" in result.answer, (
            "the caveat exists but never reaches the published answer"
        )

    @pytest.mark.asyncio
    async def test_a_catalogue_answer_with_no_figure_is_left_alone(self) -> None:
        from app.agents.analytics_agent import AnalyticsAgent, _RunState

        agent = AnalyticsAgent.__new__(AnalyticsAgent)
        agent._answer_quality_note = _none  # type: ignore[method-assign]
        agent._freshness_lines = _empty  # type: ignore[method-assign]

        state = _RunState(connection_id="c1", source_name="ga4-prod", catalogue={})
        state.catalogue_reads = 1

        result = await agent._finalise(
            state,
            _NO_CONTEXT,
            raw_answer="The available reports are overview, geo, platform, trend and events.",
            token_usage={},
        )

        assert not result.caveats, (
            f"a prose answer that states no figure needs no caveat: {result.caveats}"
        )

    def test_the_validator_warns_too(self) -> None:
        """The caveat is for the reader; the warning is for anything machine-read."""
        from app.agents.validation import AgentResultValidator

        class _Result:
            status = "success"
            answer = "July had roughly 12,400 sessions."
            raw_answer = "July had roughly 12,400 sessions."
            pending_periods: list[str] = []
            windows_opened = 0

        outcome = AgentResultValidator().validate_analytics_result(_Result())
        assert any("no report window" in w.lower() for w in outcome.warnings), (
            "the validator's only numeric warning is keyed on `pending_periods`, which "
            f"is empty when no window was ever opened. Warnings: {outcome.warnings}"
        )


#: `_finalise` touches the context only inside `_answer_quality_note`, which both
#: tests stub out — so a real AgentContext would be seven fields of noise.
_NO_CONTEXT = None


async def _none(*_args, **_kwargs):
    return None


async def _empty(*_args, **_kwargs):
    return []
