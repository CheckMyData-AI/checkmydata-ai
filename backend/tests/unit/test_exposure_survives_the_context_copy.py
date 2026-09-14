"""What a sub-agent writes onto the context must reach the response.

PRJ-01 R4/R5. `OrchestratorAgent.run` records the router's verdict with

    context = replace(context, extra={**context.extra, "route": ...})   # orchestrator.py:835

which builds a **new dict**. Every sub-agent from that point on receives copies of the
new context and writes into the new dict (`sql_agent.py:2172-2177`), while
`ConversationalAgent.run` reads the dict it constructed (`core/agent.py:92`) — the one
nothing ever wrote to. `AgentResponse.exposed_learning_ids` was therefore `[]` on every
request ever served, which makes `credit_validated_learnings` a no-op, leaves thumbs-up
and thumbs-down with nothing to attribute, and stops `times_applied` from ever moving.
R4-1, R4-2 and R4-3 are all inert behind it.

`dataclasses.replace` copies a *reference* when the field is not passed, so the fix is
to stop passing `extra=` and mutate the one dict instead. That is a property of the
boundary, not of any one agent, so it is tested as one — and locked by an AST guard,
because the defect is invisible at the call site that causes it.
"""

import ast
import pathlib
from dataclasses import replace

from app.agents.base import AgentContext

ORCHESTRATOR = pathlib.Path(__file__).resolve().parents[2] / "app" / "agents" / "orchestrator.py"


def _context() -> AgentContext:
    return AgentContext(
        project_id="p1",
        connection_config=None,
        user_question="how many orders?",
        chat_history=[],
        llm_router=None,
        tracker=None,
        workflow_id="wf-1",
        extra={},
    )


def test_a_sub_agent_write_after_a_copy_reaches_the_caller():
    """The whole chain in miniature: caller -> copy -> sub-agent write -> caller reads."""
    caller_context = _context()

    # What the orchestrator does when it records the routing decision.
    annotated = replace(caller_context, user_question=caller_context.user_question)
    annotated.extra["route"] = "query"

    # What a sub-agent does several copies deeper.
    deeper = replace(annotated, user_question="scoped sub-question")
    deeper.extra["exposed_learning_ids"] = ["lrn-1", "lrn-2"]

    assert caller_context.extra.get("exposed_learning_ids") == ["lrn-1", "lrn-2"]
    assert caller_context.extra.get("route") == "query"


def test_rebuilding_the_dict_is_what_breaks_it():
    """The defect, stated as a test, so the guard below has a reason a reader can see."""
    caller_context = _context()
    rebuilt = replace(caller_context, extra={**caller_context.extra, "route": "query"})
    rebuilt.extra["exposed_learning_ids"] = ["lrn-1"]
    assert caller_context.extra.get("exposed_learning_ids") is None


def test_the_orchestrator_never_rebuilds_the_context_extra_dict():
    tree = ast.parse(ORCHESTRATOR.read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "replace":
            continue
        # `tracker.emit(..., extra={...})` is an event payload, not the context.
        first = node.args[0] if node.args else None
        if not isinstance(first, ast.Name) or "context" not in first.id:
            continue
        for kw in node.keywords:
            if kw.arg == "extra":
                offenders.append(
                    f"orchestrator.py:{kw.value.lineno} -> replace({first.id}, extra=…)"
                )
    assert not offenders, (
        "the context's `extra` dict is being rebuilt at "
        + "; ".join(offenders)
        + ". Every sub-agent write after this point is written to a dict the caller "
        "never reads. Mutate `context.extra` in place instead."
    )
