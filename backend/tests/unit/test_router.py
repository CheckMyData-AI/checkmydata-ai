"""Unit tests for ``app.agents.router`` (LLM-driven request router)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.router import (
    _DEFAULT_ROUTE,
    _build_router_prompt,
    _extract_json,
    _parse_route_response,
    route_request,
)
from app.llm.base import Message


def test_build_router_prompt_includes_capabilities():
    prompt = _build_router_prompt(
        has_connection=True,
        has_knowledge_base=True,
        has_mcp_sources=True,
    )
    assert '"query"' in prompt
    assert '"knowledge"' in prompt
    assert '"mcp"' in prompt
    assert '"explore"' in prompt
    assert '"direct"' in prompt


def test_build_router_prompt_no_capabilities_lists_no_sources():
    prompt = _build_router_prompt(
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert "No data sources connected" in prompt
    assert '"query"' not in prompt


def test_extract_json_handles_plain_object():
    assert _extract_json('{"route": "direct", "complexity": "simple"}') == {
        "route": "direct",
        "complexity": "simple",
    }


def test_extract_json_strips_code_fences():
    raw = '```json\n{"route": "query"}\n```'
    assert _extract_json(raw) == {"route": "query"}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("not json at all") is None


def test_parse_route_response_clamps_invalid_route_to_explore():
    result = _parse_route_response(
        '{"route": "weird", "complexity": "moderate"}',
        has_connection=True,
        has_knowledge_base=True,
        has_mcp_sources=True,
    )
    assert result.route == "explore"


def test_parse_route_response_query_without_connection_falls_back():
    result = _parse_route_response(
        '{"route": "query", "complexity": "simple"}',
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert result.route == "explore"


def test_parse_route_response_clamps_estimated_queries():
    result = _parse_route_response(
        '{"route": "query", "complexity": "simple", "estimated_queries": 99}',
        has_connection=True,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert result.estimated_queries == 10


def test_parse_route_response_invalid_complexity_defaults_moderate():
    result = _parse_route_response(
        '{"route": "direct", "complexity": "huh"}',
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert result.complexity == "moderate"


def test_parse_route_response_unparseable_returns_default():
    result = _parse_route_response(
        "not json",
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert result.route == _DEFAULT_ROUTE.route


@pytest.mark.asyncio
async def test_route_request_returns_default_on_llm_failure():
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("boom"))
    result = await route_request(
        "hello",
        llm,
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
    )
    assert result.route == _DEFAULT_ROUTE.route


@pytest.mark.asyncio
async def test_route_request_parses_llm_response():
    response = MagicMock()
    response.content = (
        '{"route": "query", "complexity": "complex", '
        '"approach": "Run a join", "estimated_queries": 2, '
        '"needs_multiple_data_sources": true}'
    )
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)
    result = await route_request(
        "How many users?",
        llm,
        has_connection=True,
        has_knowledge_base=False,
        has_mcp_sources=False,
        chat_history=[Message(role="user", content="prior")],
    )
    assert result.route == "query"
    assert result.complexity == "complex"
    assert result.use_complex_pipeline is True
    assert result.is_direct is False
    assert result.needs_multiple_data_sources is True


async def test_route_request_passes_full_latest_turn():
    # I5: the latest user turn is sent to the router with the wider
    # router_last_turn_char_limit (800), not clipped to the old 500.
    response = MagicMock()
    response.content = '{"route": "query", "complexity": "simple"}'
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)
    long_q = "x" * 700
    await route_request(long_q, llm, has_connection=True)
    msgs = llm.complete.call_args.kwargs["messages"]
    final_user = msgs[-1]
    assert final_user.role == "user"
    assert len(final_user.content) == 700


def test_estimated_queries_threshold_triggers_pipeline():
    """B1: a request estimated to need >=3 sub-queries uses the pipeline even
    when the router labelled it only 'moderate'."""
    from app.agents.router import RouteResult

    rr = RouteResult(
        route="query",
        complexity="moderate",
        approach="several queries",
        estimated_queries=3,
        needs_multiple_data_sources=False,
    )
    assert rr.use_complex_pipeline is True

    rr_two = RouteResult(
        route="query",
        complexity="moderate",
        approach="a couple queries",
        estimated_queries=2,
        needs_multiple_data_sources=False,
    )
    assert rr_two.use_complex_pipeline is False


@pytest.mark.asyncio
async def test_route_request_prefers_configured_router_model(monkeypatch):
    """B1: when settings.router_model is set, the router LLM call uses it
    instead of the caller's (premium) model."""
    import app.agents.router as router_mod

    monkeypatch.setattr(router_mod.settings, "router_model", "fast-router-model")
    response = MagicMock()
    response.content = '{"route": "query", "complexity": "simple"}'
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)

    await route_request("How many users?", llm, has_connection=True, model="premium-model")

    assert llm.complete.call_args.kwargs["model"] == "fast-router-model"


@pytest.mark.asyncio
async def test_route_request_falls_back_to_caller_model(monkeypatch):
    """B1: with no router_model configured, the caller's model is used."""
    import app.agents.router as router_mod

    monkeypatch.setattr(router_mod.settings, "router_model", "")
    response = MagicMock()
    response.content = '{"route": "query", "complexity": "simple"}'
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)

    await route_request("How many users?", llm, has_connection=True, model="premium-model")

    assert llm.complete.call_args.kwargs["model"] == "premium-model"


def test_build_router_prompt_includes_git_when_has_repo():
    prompt = _build_router_prompt(
        has_connection=True,
        has_knowledge_base=False,
        has_mcp_sources=False,
        has_repo=True,
    )
    assert '"git"' in prompt


def test_build_router_prompt_omits_git_without_repo():
    prompt = _build_router_prompt(
        has_connection=True,
        has_knowledge_base=False,
        has_mcp_sources=False,
        has_repo=False,
    )
    assert '"git"' not in prompt


def test_parse_route_response_git_with_repo_kept():
    result = _parse_route_response(
        '{"route": "git", "complexity": "moderate"}',
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
        has_repo=True,
    )
    assert result.route == "git"


def test_parse_route_response_git_without_repo_downgrades():
    result = _parse_route_response(
        '{"route": "git", "complexity": "moderate"}',
        has_connection=False,
        has_knowledge_base=False,
        has_mcp_sources=False,
        has_repo=False,
    )
    assert result.route == "explore"


def test_needs_multiple_data_sources_triggers_pipeline_when_not_complex():
    """A non-complex request that spans data sources still uses the pipeline."""
    from app.agents.router import RouteResult

    rr = RouteResult(
        route="explore",
        complexity="moderate",
        approach="combine db + mcp",
        estimated_queries=2,
        needs_multiple_data_sources=True,
    )
    assert rr.use_complex_pipeline is True

    rr_single = RouteResult(
        route="query",
        complexity="moderate",
        approach="one query",
        estimated_queries=1,
        needs_multiple_data_sources=False,
    )
    assert rr_single.use_complex_pipeline is False
