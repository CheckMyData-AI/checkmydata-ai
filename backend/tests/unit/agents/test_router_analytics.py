"""T14 gap 3 — the router must be able to route to an analytics source.

T13 wired ``has_analytics_sources`` through the *orchestrator* — the tool is
offered, the pipeline gate counts analytics as a data source, and the direct
route escalates via the NEEDS_DATA sentinel. But the **router** was never told,
so an analytics-only project still got a capability block that read "No data
sources connected" and most questions were classified ``direct``. The T13
escape recovers from that, at the cost of a whole extra LLM round trip on every
analytics question — the model has to answer, notice it cannot, emit the
sentinel, and be re-run through the tool loop.

Telling the router removes the round trip: the capability is stated, an
``analytics`` route exists, and a GA4 question is classified as data on the
first call.

The route is validated the same way ``mcp`` is — a model that names a route the
project cannot serve is downgraded to ``explore`` rather than trusted.

No network: the LLM router is a mock throughout.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import app.agents.orchestrator as orchestrator_module
from app.agents.router import (
    _build_router_prompt,
    _parse_route_response,
    route_request,
)

# ---------------------------------------------------------------------------
# The capability block
# ---------------------------------------------------------------------------

_NO_SOURCES = "No data sources connected"


class TestRouterPromptStatesAnalytics:
    def test_analytics_only_project_states_the_capability(self) -> None:
        prompt = _build_router_prompt(
            has_connection=False,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=True,
        )

        assert _NO_SOURCES not in prompt, (
            "an analytics-only project HAS a data source; the router must not be "
            f"told otherwise. Prompt:\n{prompt}"
        )
        assert "Google Analytics 4" in prompt
        assert '"analytics"' in prompt

    def test_database_and_analytics_states_both(self) -> None:
        prompt = _build_router_prompt(
            has_connection=True,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=True,
        )

        assert _NO_SOURCES not in prompt
        assert "A database is connected" in prompt
        assert "Google Analytics 4" in prompt
        assert '"query"' in prompt
        assert '"analytics"' in prompt

    def test_capability_names_what_the_data_actually_is(self) -> None:
        """A bare "analytics is connected" tells the model nothing routable."""
        prompt = _build_router_prompt(
            has_connection=False,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=True,
        )

        lowered = prompt.lower()
        for token in ("traffic", "users", "events", "revenue", "collected"):
            assert token in lowered, f"router prompt should mention {token!r}"

    def test_absent_without_analytics_sources(self) -> None:
        prompt = _build_router_prompt(
            has_connection=True,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=False,
        )

        assert '"analytics"' not in prompt
        assert "Google Analytics 4" not in prompt

    def test_a_project_with_nothing_connected_still_says_so(self) -> None:
        prompt = _build_router_prompt(
            has_connection=False,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=False,
        )

        assert _NO_SOURCES in prompt


# ---------------------------------------------------------------------------
# Route validation
# ---------------------------------------------------------------------------


class TestAnalyticsRouteValidation:
    def test_analytics_route_kept_when_the_project_has_analytics(self) -> None:
        result = _parse_route_response(
            '{"route": "analytics", "complexity": "simple", "approach": "read GA4", '
            '"estimated_queries": 1, "needs_multiple_data_sources": false}',
            has_connection=False,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=True,
        )

        assert result.route == "analytics"
        assert result.is_direct is False

    def test_analytics_route_downgraded_without_analytics(self) -> None:
        """Same guard as ``mcp``: never trust a route the project cannot serve."""
        result = _parse_route_response(
            '{"route": "analytics", "complexity": "simple", "approach": "read GA4", '
            '"estimated_queries": 1, "needs_multiple_data_sources": false}',
            has_connection=True,
            has_knowledge_base=False,
            has_mcp_sources=False,
            has_analytics_sources=False,
        )

        assert result.route == "explore"


# ---------------------------------------------------------------------------
# route_request threads the flag
# ---------------------------------------------------------------------------


class TestRouteRequestThreadsTheFlag:
    async def test_system_prompt_carries_the_capability(self) -> None:
        llm = MagicMock()
        llm.complete = AsyncMock(
            return_value=MagicMock(
                content=(
                    '{"route": "analytics", "complexity": "simple", '
                    '"approach": "read GA4", "estimated_queries": 1, '
                    '"needs_multiple_data_sources": false}'
                )
            )
        )

        result = await route_request(
            "How many users came from organic search last week?",
            llm,
            has_analytics_sources=True,
        )

        system = llm.complete.call_args.kwargs["messages"][0]
        assert system.role == "system"
        assert "Google Analytics 4" in system.content
        assert _NO_SOURCES not in system.content
        assert result.route == "analytics"

    async def test_flag_defaults_off(self) -> None:
        llm = MagicMock()
        llm.complete = AsyncMock(return_value=MagicMock(content='{"route": "direct"}'))

        await route_request("hello", llm)

        system = llm.complete.call_args.kwargs["messages"][0]
        assert '"analytics"' not in system.content


# ---------------------------------------------------------------------------
# The orchestrator's call site
# ---------------------------------------------------------------------------


class TestOrchestratorPassesTheFlag:
    def test_route_request_call_site_forwards_has_analytics(self) -> None:
        """Static check: the ``route_request(...)`` call must pass the flag.

        Driving ``run()`` proves it for one path only; reading the call site
        proves it for the single place the router is ever invoked, and fails
        loudly if a future edit drops the keyword.
        """
        source = Path(inspect.getfile(orchestrator_module)).read_text(encoding="utf-8")
        tree = ast.parse(source)

        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "route_request"
        ]
        assert calls, "orchestrator no longer calls route_request"

        for call in calls:
            kwargs = {kw.arg for kw in call.keywords if kw.arg}
            assert "has_mcp_sources" in kwargs, (
                f"unexpected route_request call at line {call.lineno}: no has_mcp_sources"
            )
            assert "has_analytics_sources" in kwargs, (
                "route_request must be called with has_analytics_sources "
                f"(line {call.lineno}, got {sorted(kwargs)})"
            )

    def test_the_flag_comes_from_the_analytics_probe(self) -> None:
        """It must be the probe's value, not a literal."""
        source = Path(inspect.getfile(orchestrator_module)).read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "route_request"
            ):
                for kw in node.keywords:
                    if kw.arg == "has_analytics_sources":
                        assert isinstance(kw.value, ast.Name), (
                            "has_analytics_sources must be the probe result, "
                            f"got {ast.dump(kw.value)}"
                        )
                        assert kw.value.id == "has_analytics"
