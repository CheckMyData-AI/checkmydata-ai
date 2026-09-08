"""The nightly sync passed within fifteen seconds of its ceiling and said nothing.

Measured on production: `daily_knowledge_sync_job_timeout_seconds` is 7200
(`config.py:550`, applied at `worker.py:372`), and the longest **completed** run took
**7 214.9 s**. The longest failed one took 7 497 s.

7 214.9 against 7 200 is not a comfortable margin; it is a run that finished by luck.
The ARQ timeout does not warn on the way up — it cancels — so the first symptom of a
repository growing past the budget is a night that simply did not sync, and the run
before it looked exactly like a success.

The rule is deliberately about the RATIO rather than a second threshold constant. A
ceiling raised without moving the alarm would leave the alarm permanently silent, which
is the failure mode of every hard-coded warning threshold that sits beside a
configurable limit. And the timeout is read at the moment of the check rather than
captured at start-up, so a run that outlives a config change is judged against the
budget that will actually cancel it.
"""

from __future__ import annotations

import pytest

from app.services.daily_knowledge_sync_service import (
    BUDGET_WARNING_FRACTION,
    budget_warning,
)


class TestTheThreshold:
    def test_a_comfortable_run_says_nothing(self) -> None:
        assert budget_warning(elapsed_seconds=0.5 * 7200, timeout_seconds=7200) is None

    def test_just_under_the_fraction_says_nothing(self) -> None:
        assert budget_warning(elapsed_seconds=0.84 * 7200, timeout_seconds=7200) is None

    def test_just_over_the_fraction_warns(self) -> None:
        assert budget_warning(elapsed_seconds=0.86 * 7200, timeout_seconds=7200) is not None

    def test_the_production_run_that_prompted_this_would_have_warned(self) -> None:
        """7 214.9 s actually exceeded the 7 200 s budget and still completed — ARQ's
        timeout is not perfectly punctual. The alarm must fire for that, obviously, but
        the point is that it fires long before it."""
        assert budget_warning(elapsed_seconds=7214.9, timeout_seconds=7200) is not None
        assert budget_warning(elapsed_seconds=6200, timeout_seconds=7200) is not None, (
            "6 200 s is 86% of the budget and is the run worth warning about — by 7 214 "
            "the night has already been decided"
        )

    def test_the_message_carries_both_numbers_and_the_percentage(self) -> None:
        """An alarm that says 'nearly at the limit' without saying what the limit is
        cannot be acted on: the operator's next move is to raise the ceiling or split the
        work, and both need the two figures."""
        msg = budget_warning(elapsed_seconds=6480, timeout_seconds=7200)
        assert msg is not None
        assert "6480" in msg
        assert "7200" in msg
        assert "90" in msg


class TestTheRuleTracksTheLimitItGuards:
    def test_raising_the_ceiling_moves_the_alarm_with_it(self) -> None:
        """A hard-coded second threshold is the failure mode this avoids: raise the
        timeout to 14400 and a constant 6120 s alarm would fire on every ordinary run
        forever, so somebody would delete it."""
        assert budget_warning(elapsed_seconds=6480, timeout_seconds=7200) is not None
        assert budget_warning(elapsed_seconds=6480, timeout_seconds=14400) is None

    def test_the_fraction_is_named_once(self) -> None:
        assert 0.5 < BUDGET_WARNING_FRACTION < 1.0

    @pytest.mark.parametrize("bad", [0, -1])
    def test_a_missing_timeout_is_not_an_alarm(self, bad: int) -> None:
        """Degrade quiet, not loud. A zero or negative timeout means the caller could not
        determine the budget; warning on every run would train the operator to ignore the
        line that matters."""
        assert budget_warning(elapsed_seconds=99999, timeout_seconds=bad) is None


class TestTheServiceUsesIt:
    def test_run_for_project_checks_the_budget_it_will_be_cancelled_against(self) -> None:
        """Source-level: the check sits in a method that needs a worker, a coordinator
        and three sessions to run. What it pins is that the timeout is read from
        `settings` AT THE CHECK — a value captured at start-up would judge a long run
        against a budget that is no longer the one about to cancel it."""
        import inspect
        import re

        from app.services import daily_knowledge_sync_service as mod

        src = inspect.getsource(mod.DailyKnowledgeSyncService.run_for_project)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        flat = " ".join(body.split())
        assert "budget_warning(" in flat, "the outcome path does not consult the budget"
        assert "settings.daily_knowledge_sync_job_timeout_seconds" in flat, (
            "the timeout must be read where the check happens, not captured earlier"
        )
