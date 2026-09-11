"""The learning extraction that follows nearly every answer was spending off the books.

`learning_analyzer_mode` defaults to `llm_first`, and V2 deliberately dropped the
"≥2 attempts" gate so every outcome produces a learning — so `LearningAnalyzer._llm_extract`
is the highest-frequency user-triggered LLM path in the product. It ran on a class-level
`LLMRouter()` built with no sink, i.e. `NullUsageSink`, so those tokens counted against no
daily limit, no monthly limit and no plan limit and appeared in no figure on
`/api/usage/stats` (BILL-10, audit 2026-09-09).

**The fix needed no new plumbing, which is why it is worth a test rather than a comment.**
`SQLAgent` already holds the request's router — the orchestrator builds it with a
`DbUsageSink` bound to the asking user — and `LearningAnalyzer` already accepts one. The
call sites simply did not pass it, so the analysis of a user's question was attributed to
nobody while the question itself was attributed correctly.
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).parents[1].parent / "app"


def _call_kwargs(path: pathlib.Path, func_name: str, callee: str) -> list[list[str]]:
    """Keyword names passed to every ``callee(...)`` inside ``func_name``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[list[str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func_name
        ):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and getattr(child.func, "id", "") == callee:
                out.append(
                    [kw.arg or "" for kw in child.keywords] + ["<positional>"] * len(child.args)
                )
    return out


def test_sql_agent_hands_its_own_router_to_the_learning_analyzer() -> None:
    """`self._llm` carries the asking user's sink; a fresh router carries nobody's."""
    calls = _call_kwargs(APP / "agents" / "sql_agent.py", "_extract_learnings", "LearningAnalyzer")
    assert calls, "LearningAnalyzer is no longer constructed in _extract_learnings"
    for kwargs in calls:
        assert kwargs != [], (
            "LearningAnalyzer() is built with no router, so it falls back to the shared "
            "bare one and the extraction spends tokens nobody is charged for (BILL-10)"
        )


def test_the_batch_analyzer_is_metered_too() -> None:
    """`LLMAnalyzer` fires at ≥3 attempts — the same tokens, on a worse day for the user."""
    calls = _call_kwargs(APP / "agents" / "sql_agent.py", "_extract_learnings", "LLMAnalyzer")
    assert calls, "LLMAnalyzer is no longer constructed in _extract_learnings"
    for kwargs in calls:
        assert kwargs != [], "LLMAnalyzer() is built with no router (BILL-10)"


def test_the_feedback_route_meters_its_analyzer() -> None:
    """`POST /api/chat/feedback` re-runs extraction on a thumbs-down, with a user in scope."""
    route = APP / "api" / "routes" / "chat_feedback.py"
    calls = _call_kwargs(route, "submit_feedback", "LearningAnalyzer")
    if not calls:  # the construction may live in a helper; find it wherever it is
        tree = ast.parse(route.read_text(encoding="utf-8"))
        calls = [
            [kw.arg or "" for kw in n.keywords] + ["<positional>"] * len(n.args)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "LearningAnalyzer"
        ]
    assert calls, "LearningAnalyzer is no longer constructed in chat_feedback"
    for kwargs in calls:
        assert kwargs != [], (
            "the feedback route builds an unmetered analyzer while holding the user id "
            "that should be charged"
        )
