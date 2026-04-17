"""Unified LLM-driven router for the orchestrator.

Replaces the separate intent classifier + _is_complex heuristic with
a single LLM call that returns structured routing information.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_ROUTER_MAX_TOKENS = 200


@dataclass
class RouteResult:
    route: str  # "direct" | "query" | "knowledge" | "mcp" | "explore"
    complexity: str  # "simple" | "moderate" | "complex"
    approach: str
    estimated_queries: int
    needs_multiple_data_sources: bool
    raw: dict | None = None

    @property
    def is_direct(self) -> bool:
        return self.route == "direct"

    @property
    def use_complex_pipeline(self) -> bool:
        return self.complexity == "complex"


_DEFAULT_ROUTE = RouteResult(
    route="explore",
    complexity="moderate",
    approach="Unable to classify — using full capabilities to answer.",
    estimated_queries=2,
    needs_multiple_data_sources=False,
)

_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")


def _build_router_prompt(
    *,
    has_connection: bool,
    has_knowledge_base: bool,
    has_mcp_sources: bool,
) -> str:
    capabilities: list[str] = []
    routes: list[str] = []

    routes.append('"direct" — greetings, thanks, meta-questions, casual conversation, '
                  "follow-ups about already-displayed results that need no new data")

    if has_connection:
        capabilities.append("A database is connected (SQL queries are available).")
        routes.append('"query" — questions requiring database queries for numbers, '
                      "statistics, records, or analytics")
    if has_knowledge_base:
        capabilities.append("A project knowledge base is indexed (code, docs, architecture).")
        routes.append('"knowledge" — questions about project code, architecture, or documentation')
    if has_mcp_sources:
        capabilities.append("External MCP data sources are connected.")
        routes.append('"mcp" — questions requiring external MCP-connected service data')

    routes.append('"explore" — spans multiple capabilities, or you are unsure which applies')

    cap_block = (
        "\n".join(f"- {c}" for c in capabilities)
        if capabilities
        else "- No data sources connected."
    )
    route_block = "\n".join(f"- {r}" for r in routes)

    return (
        "You are a request router for an AI data assistant.\n\n"
        f"Available capabilities:\n{cap_block}\n\n"
        f"Possible routes:\n{route_block}\n\n"
        "Given the user's message and recent conversation context, respond with a single "
        "JSON object:\n"
        "{\n"
        '  "route": "<one of the routes above>",\n'
        '  "complexity": "simple" | "moderate" | "complex",\n'
        '  "approach": "<1-2 sentence plan for answering this question>",\n'
        '  "estimated_queries": <integer 0-5>,\n'
        '  "needs_multiple_data_sources": true/false\n'
        "}\n\n"
        "Complexity guide:\n"
        "- simple: single straightforward lookup or aggregation\n"
        "- moderate: needs joins, grouping, or 2-3 steps\n"
        "- complex: multi-dimensional analysis, temporal comparisons, cross-referencing, "
        "or questions requiring multiple sequential queries whose results feed into each other\n\n"
        "Reply ONLY with the JSON object. No other text."
    )


def _extract_json(raw: str) -> dict | None:
    raw = raw.strip()
    if "```" in raw:
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    for start_char in ("{", "["):
        idx = raw.find(start_char)
        if idx > 0:
            raw = raw[idx:]
            break

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    m = _JSON_OBJ_RE.search(raw)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


_VALID_ROUTES = {"direct", "query", "knowledge", "mcp", "explore"}
_VALID_COMPLEXITY = {"simple", "moderate", "complex"}


def _parse_route_response(
    raw: str,
    *,
    has_connection: bool,
    has_knowledge_base: bool,
    has_mcp_sources: bool,
) -> RouteResult:
    data = _extract_json(raw)
    if data is None:
        logger.warning("Router returned unparseable response: %s", raw[:200])
        return _DEFAULT_ROUTE

    route = str(data.get("route", "explore")).strip().lower()
    complexity = str(data.get("complexity", "moderate")).strip().lower()
    approach = str(data.get("approach", ""))
    est_queries = data.get("estimated_queries", 1)
    multi_src = bool(data.get("needs_multiple_data_sources", False))

    if route not in _VALID_ROUTES:
        route = "explore"
    if route == "query" and not has_connection:
        route = "explore"
    if route == "knowledge" and not has_knowledge_base:
        route = "explore"
    if route == "mcp" and not has_mcp_sources:
        route = "explore"

    if complexity not in _VALID_COMPLEXITY:
        complexity = "moderate"

    try:
        est_queries = max(0, min(int(est_queries), 10))
    except (TypeError, ValueError):
        est_queries = 1

    return RouteResult(
        route=route,
        complexity=complexity,
        approach=approach,
        estimated_queries=est_queries,
        needs_multiple_data_sources=multi_src,
        raw=data,
    )


async def route_request(
    question: str,
    llm_router: LLMRouter,
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    chat_history: list[Message] | None = None,
    preferred_provider: str | None = None,
    model: str | None = None,
) -> RouteResult:
    """Route the user's request via a single LLM call.

    Returns a ``RouteResult`` with route, complexity, and approach.
    Falls back to ``_DEFAULT_ROUTE`` on any failure.
    """
    system_prompt = _build_router_prompt(
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        has_mcp_sources=has_mcp_sources,
    )

    messages: list[Message] = [Message(role="system", content=system_prompt)]

    if chat_history:
        tail = chat_history[-settings.history_tail_messages :]
        for m in tail:
            if m.role in ("user", "assistant") and m.content:
                snippet = m.content[:200]
                messages.append(Message(role=m.role, content=snippet))

    messages.append(Message(role="user", content=question[:500]))

    try:
        resp = await llm_router.complete(
            messages=messages,
            max_tokens=_ROUTER_MAX_TOKENS,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=model,
        )
    except Exception:
        logger.debug("Router LLM call failed, using default route", exc_info=True)
        return _DEFAULT_ROUTE

    result = _parse_route_response(
        resp.content,
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        has_mcp_sources=has_mcp_sources,
    )
    logger.info(
        "Router: route=%s complexity=%s est_queries=%d approach=%s",
        result.route,
        result.complexity,
        result.estimated_queries,
        result.approach[:80],
    )
    return result
