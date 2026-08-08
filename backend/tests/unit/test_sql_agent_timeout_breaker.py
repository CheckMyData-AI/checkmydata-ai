"""The SQL tool loop must stop for a database that has stopped answering.

Production trace 2026-08-06 11:39:24: six LLM calls and five `execute_query` tool
calls, every one of them ending in a 30 s timeout, 277.8 s inside the tool. The loop
is bounded by `max_sql_iterations` (10) and by nothing else — the orchestrator's
180 s budget is checked between *orchestrator* iterations, and the whole SQL agent
runs inside one of them, so it could not intervene. The request died at the route's
360 s ceiling.

Two independent stops are added here: a consecutive-timeout breaker and a wall-clock
deadline. Both live in `run()`'s call frame, never on the agent — `chat.py` builds
`ConversationalAgent()` at module level, and one `SQLAgent` instance therefore serves
every request in the process (up to `max_concurrent_agent_calls` at a time). State on
`self` would let one tenant's dead database break another tenant's loop.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.sql_agent import SQLAgent
from app.config import Settings


class TestSettings:
    def test_threshold_and_deadline_flag_exist_with_documented_defaults(self):
        from app.config import settings

        assert settings.sql_timeout_breaker_threshold == 2
        assert settings.sql_agent_deadline_enabled is True

    def test_a_non_positive_threshold_raises_at_boot(self):
        """Silently disabling the breaker is the failure this rejects.

        A `0` here would mean "never trip", which reads as "configured" and behaves
        as "absent" — the same class of quiet idling the analytics settings were
        given boot validation to prevent.
        """
        for bad in (0, -1):
            with pytest.raises(ValueError, match="SQL_TIMEOUT_BREAKER_THRESHOLD"):
                Settings(sql_timeout_breaker_threshold=bad)


class TestValidationConfigIsNotSharedBetweenRequests:
    """Regression for a pre-existing cross-request leak (carry-over K10).

    `run()` used to stash its caller's remaining budget on `self._wall_clock_remaining`
    and `_build_validation_config` read it back off `self`. With one agent instance
    serving concurrent requests, whoever wrote last decided everyone's query timeout.
    """

    def test_build_validation_config_takes_the_budget_as_an_argument(self):
        agent = SQLAgent()

        generous = agent._build_validation_config(wall_clock_remaining=None)
        squeezed = agent._build_validation_config(wall_clock_remaining=20.0)

        # 20 s remaining -> half of it is the ceiling for a single query.
        assert squeezed.query_timeout_seconds == 10
        assert generous.query_timeout_seconds > squeezed.query_timeout_seconds

    def test_the_agent_keeps_no_per_request_budget_on_itself(self):
        agent = SQLAgent()
        agent._build_validation_config(wall_clock_remaining=20.0)

        assert not hasattr(agent, "_wall_clock_remaining"), (
            "per-request state on a process-wide singleton is a cross-tenant leak"
        )

    async def test_concurrent_callers_do_not_overwrite_each_others_budget(self):
        agent = SQLAgent()

        async def build(remaining: float) -> int:
            await asyncio.sleep(0)  # force interleaving
            cfg = agent._build_validation_config(wall_clock_remaining=remaining)
            await asyncio.sleep(0)
            return cfg.query_timeout_seconds

        wide, narrow = await asyncio.gather(build(120.0), build(20.0))

        assert narrow == 10
        assert wide > narrow
