"""Unified LLM-driven router for the orchestrator.

Replaces the separate intent classifier + _is_complex heuristic with
a single LLM call that returns structured routing information.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import settings
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

# L1: 200 tokens could truncate the JSON when the model writes a longer
# "approach" sentence, corrupting the parse and forcing the default route. 512
# comfortably fits the small fixed schema plus a 1-2 sentence approach.
_ROUTER_MAX_TOKENS = 512
# A request estimated to need at least this many sub-queries is treated as
# multi-step and routed to the full pipeline (matches ContextPlanner's heuristic).
_PIPELINE_ESTIMATED_QUERIES_THRESHOLD = 3


@dataclass
class RouteResult:
    route: str  # "direct" | "query" | "knowledge" | "git" | "mcp" | "explore"
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
        # A request is routed to the multi-stage pipeline when the router calls
        # it complex OR when it needs to combine multiple data sources OR when
        # it is estimated to need several (>=3) sub-queries. The last two
        # signals were previously parsed but never acted on (estimated_queries
        # was pure contract drift), so multi-step questions were silently
        # handled by the single-loop path. The >=3 threshold matches the
        # ContextPlanner's own multi-query heuristic.
        return (
            self.complexity == "complex"
            or self.needs_multiple_data_sources
            or self.estimated_queries >= _PIPELINE_ESTIMATED_QUERIES_THRESHOLD
        )


_DEFAULT_ROUTE = RouteResult(
    route="explore",
    complexity="moderate",
    approach="Unable to classify — using full capabilities to answer.",
    estimated_queries=2,
    needs_multiple_data_sources=False,
)


def _build_router_prompt(
    *,
    has_connection: bool,
    has_knowledge_base: bool,
    has_mcp_sources: bool,
    has_repo: bool = False,
) -> str:
    capabilities: list[str] = []
    routes: list[str] = []

    routes.append(
        '"direct" — greetings, thanks, meta-questions, casual conversation, '
        "follow-ups about already-displayed results that need no new data"
    )

    if has_connection:
        capabilities.append("A database is connected (SQL queries are available).")
        routes.append(
            '"query" — questions requiring database queries for numbers, '
            "statistics, records, or analytics"
        )
    if has_knowledge_base:
        capabilities.append("A project knowledge base is indexed (code, docs, architecture).")
        routes.append('"knowledge" — questions about project code, architecture, or documentation')
    if has_repo:
        capabilities.append("A live Git repository clone is available (commit history, releases).")
        routes.append(
            '"git" — questions about commit history, code changes/diffs, who changed '
            "what, release timelines, or commit review signals"
        )
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
        'Routing guidance: choose "direct" ONLY for conversational/meta messages '
        "(greetings, thanks, clarifications) or follow-ups about results already shown. "
        "If the answer depends on actual data from a connected source, do NOT choose "
        '"direct" — pick the matching data route (or "explore" when unsure).\n\n'
        "Reply ONLY with the JSON object. No other text."
    )


def _extract_json(raw: str) -> dict | None:
    """Extract the first JSON object from an LLM reply.

    Robust to code fences, leading prose, trailing prose, and nested objects
    (L1): we scan for each candidate ``{``/``[`` start and use
    ``JSONDecoder.raw_decode`` — which parses one complete JSON value and stops,
    correctly handling nested braces and ignoring any trailing text.
    """
    raw = raw.strip()
    if "```" in raw:
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for start_char in ("{", "["):
        idx = raw.find(start_char)
        while idx != -1:
            try:
                data, _end = decoder.raw_decode(raw[idx:])
            except json.JSONDecodeError:
                idx = raw.find(start_char, idx + 1)
                continue
            if isinstance(data, list):
                data = data[0] if data else None
            if isinstance(data, dict):
                return data
            idx = raw.find(start_char, idx + 1)

    return None


_VALID_ROUTES = {"direct", "query", "knowledge", "git", "mcp", "explore"}
_VALID_COMPLEXITY = {"simple", "moderate", "complex"}

# ORCH-R03: cheap data-intent conjunction heuristic so that multi-step questions
# that the LLM under-estimated still reach the pipeline threshold.
_DATA_CONJUNCTIONS = (
    " and ",
    " then ",
    "compare",
    " by ",
    " vs ",
    "over time",
    " each ",
)
_HEURISTIC_QUERIES_CAP = 5


def _heuristic_queries(question: str) -> int:
    """Count data-intent conjunctions and return a capped estimate."""
    q_lower = question.lower()
    return min(
        sum(1 for token in _DATA_CONJUNCTIONS if token in q_lower),
        _HEURISTIC_QUERIES_CAP,
    )


def _parse_route_response(
    raw: str,
    *,
    has_connection: bool,
    has_knowledge_base: bool,
    has_mcp_sources: bool,
    has_repo: bool = False,
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
    if route == "git" and not has_repo:
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
    has_repo: bool = False,
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
        has_repo=has_repo,
    )

    messages: list[Message] = [Message(role="system", content=system_prompt)]

    if chat_history:
        tail = chat_history[-settings.history_tail_messages :]
        for m in tail:
            if m.role in ("user", "assistant") and m.content:
                snippet = m.content[:200]
                messages.append(Message(role=m.role, content=snippet))

    messages.append(Message(role="user", content=question[: settings.router_last_turn_char_limit]))

    # The routing classification is a cheap, well-bounded task — prefer a fast
    # model configured via ``router_model`` so it does not burn the user's
    # premium model on every turn. Falls back to the caller's model when unset.
    effective_model = settings.router_model or model

    try:
        resp = await llm_router.complete(
            messages=messages,
            max_tokens=_ROUTER_MAX_TOKENS,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=effective_model,
        )
    except Exception:
        logger.debug("Router LLM call failed, using default route", exc_info=True)
        return _DEFAULT_ROUTE

    result = _parse_route_response(
        resp.content,
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        has_mcp_sources=has_mcp_sources,
        has_repo=has_repo,
    )

    # ORCH-R03: OR-in the cheap heuristic so under-estimated multi-step questions
    # still reach the pipeline threshold.  Log estimated-vs-heuristic for
    # calibration.
    heuristic = _heuristic_queries(question)
    calibrated = max(result.estimated_queries, heuristic)
    if calibrated != result.estimated_queries:
        logger.debug(
            "Router: heuristic raised estimated_queries %d → %d (question len=%d)",
            result.estimated_queries,
            calibrated,
            len(question),
        )
        from dataclasses import replace as _replace

        result = _replace(result, estimated_queries=calibrated)

    logger.info(
        "Router: route=%s complexity=%s est_queries=%d (heuristic=%d) approach=%s",
        result.route,
        result.complexity,
        result.estimated_queries,
        heuristic,
        result.approach[:80],
    )
    return result
