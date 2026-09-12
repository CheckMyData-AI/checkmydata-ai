"""The lowest role could write to the customer's database, and nine smaller drifts.

P3 row 24; COR-04, COR-05, COR-06, COR-08 and FE-04/06/07/09/10/11 (the frontend half
is guarded in `frontend/src/__tests__/`).

**COR-06 is not polish and does not belong in a row called one.** The role ladder gates
workspace mutations — a dashboard needs `editor`, a schedule needs `owner` — and no
execution path distinguishes a viewer from an owner for SQL against the *customer's*
database. On a connection with `is_read_only=False` a viewer can save a note whose
`sql_query` is `DELETE FROM orders WHERE 1=1` and execute it: `SafetyGuard(ALLOW_DML)`
blocks only DDL. The product's own scenarios treat viewer as read-only for far less
consequential surfaces — *"viewer opens the workspace → cards render read-only with no
edit/index/delete"* — while the most consequential action available had no role gate at
all.

**COR-08** — `broadcast_external` writes `_workflow_owners` and `_ended_workflows` with
no `_OWNERS_MAX` check and no `_ENDED_SET_MAX` trim, and those caps are applied only in
`begin()`/`end()` — which are never called on the web dyno for a worker workflow. So the
bounds guarding these maps are dead code on the process that serves users. Separately an
`_active_workflows` entry created by a cross-process `pipeline_start` is removed only by
a matching `pipeline_end`; drop that one Redis message and `/api/tasks/active` reports
the workflow running for ever.

**COR-04** — `/api/chat/estimate` takes no session, so the meter reports a constant as
"history remaining" and cannot move with the conversation, and `rotation_imminent`
measures a different quantity from the one that triggers rotation.

**COR-05** — the multilingual promise holds only where an LLM writes the text; every
static answer path ships English verbatim, including the ones the README says carry the
language rule.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import time
from types import SimpleNamespace
from typing import Any

_BACKEND = pathlib.Path(__file__).resolve().parents[2]
_ROUTES = _BACKEND / "app" / "api" / "routes"


def _requires_role_above_viewer(node: ast.AST) -> bool:
    """True when the body calls `require_role(..., "owner" | "editor")`.

    Read from the call rather than from the text: `ast.unparse` normalises quoting,
    so a substring search for `'"owner"'` silently matches nothing.
    """
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
        if name != "require_role":
            continue
        supplied = [*call.args, *(kw.value for kw in call.keywords)]
        if any(isinstance(a, ast.Constant) and a.value in ("owner", "editor") for a in supplied):
            return True
    return False


class TestAViewerCannotWriteToTheCustomersDatabase:
    """COR-06 — the shape of the gate.

    Whether the gate WORKS is measured over HTTP in
    `tests/integration/test_a_viewer_cannot_write_to_the_database.py`, with a real
    viewer, a real writable connection and a real `DELETE`. What is checked here is
    that a future route cannot reach the same executor without asking.
    """

    def test_the_gate_is_one_helper_rather_than_a_literal_per_route(self) -> None:
        from app.services.membership_service import MembershipService

        assert hasattr(MembershipService, "require_write_role"), (
            "spelling the role inline at each SQL-execution site is how notes and "
            "batch came to disagree with `dashboards.py` and `schedules.py` in the "
            "first place"
        )

    def test_every_route_that_runs_customer_sql_asks_for_a_role_above_viewer(
        self,
    ) -> None:
        """Discovered, not listed: a new execution route joins this check by existing.

        The marker is building a `SafetyGuard` or enqueueing `run_batch` — the two
        ways a route in this application sends a caller's statement to the customer's
        database. A route that does either and settles for `viewer` is COR-06 again.
        """
        offenders: list[str] = []
        for path in sorted(_ROUTES.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                body = ast.unparse(node)
                # Read the literal from the AST: `ast.unparse` normalises quoting, so
                # a substring search for a double-quoted name matches nothing. That
                # exact slip let a planted defect in `execute_batch` pass this sweep.
                names = {
                    n.value
                    for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                }
                runs_sql = "SafetyGuard(" in body or "run_batch" in names
                if not runs_sql:
                    continue
                asks = "require_write_role" in body or _requires_role_above_viewer(node)
                if not asks:
                    offenders.append(f"{path.name}:{node.name}")
        assert not offenders, (
            f"{offenders} send a caller's SQL to the customer's database without "
            "asking for a role above `viewer` (COR-06)"
        )


class TestTheTrackerBoundsHoldOnEveryProcess:
    """COR-08 — measured through the maps, not read off the source.

    `broadcast_external` is the path every WORKER workflow takes to reach the web
    dyno, and it wrote `_workflow_owners` and `_ended_workflows` with no cap: those
    were applied only in `begin()`/`end()`, which the web dyno never calls for a
    worker workflow. So the bounds guarding these maps were dead code on the process
    that serves users.
    """

    @staticmethod
    def _external(step: str, wf_id: str, *, pipeline: str = "", ts: float = 0.0) -> Any:
        from app.core.workflow_tracker import WorkflowEvent

        return WorkflowEvent(
            workflow_id=wf_id,
            step=step,
            status="started" if step == "pipeline_start" else "completed",
            detail="",
            pipeline=pipeline,
            extra={"user_id": "u1", "project_id": "p1"},
            timestamp=ts,
        )

    async def test_the_owners_map_is_bounded_on_the_web_dyno(self) -> None:
        from app.core.workflow_tracker import BACKGROUND_PIPELINES, WorkflowTracker

        tracker = WorkflowTracker()
        pipeline = next(iter(BACKGROUND_PIPELINES))
        for i in range(tracker._OWNERS_MAX + 50):
            await tracker.broadcast_external(
                self._external("pipeline_start", f"wf-{i}", pipeline=pipeline, ts=time.time())
            )
        assert len(tracker._workflow_owners) <= tracker._OWNERS_MAX, (
            f"{len(tracker._workflow_owners)} owner entries against a cap of "
            f"{tracker._OWNERS_MAX}: every worker workflow reaches the web dyno "
            "through `broadcast_external`, and the cap lived in `begin()` (COR-08)"
        )

    async def test_the_ended_set_is_bounded_on_the_web_dyno(self) -> None:
        from app.core.workflow_tracker import WorkflowTracker

        tracker = WorkflowTracker()
        for i in range(tracker._ENDED_SET_MAX + 50):
            await tracker.broadcast_external(self._external("pipeline_end", f"wf-{i}"))
        assert len(tracker._ended_workflows) <= tracker._ENDED_SET_MAX, (
            f"{len(tracker._ended_workflows)} ended ids against a cap of "
            f"{tracker._ENDED_SET_MAX}: the trim lived in `end()` (COR-08)"
        )

    async def test_a_workflow_whose_end_never_arrives_stops_being_reported(self) -> None:
        """Drop one `pipeline_end` and the workflow was 'running' for ever."""
        from app.core.workflow_tracker import BACKGROUND_PIPELINES, WorkflowTracker

        tracker = WorkflowTracker()
        pipeline = next(iter(BACKGROUND_PIPELINES))
        lost = time.time() - tracker._active_max_age_seconds() - 1
        await tracker.broadcast_external(
            self._external("pipeline_start", "wf-lost", pipeline=pipeline, ts=lost)
        )
        live = time.time()
        await tracker.broadcast_external(
            self._external("pipeline_start", "wf-live", pipeline=pipeline, ts=live)
        )

        reported = {
            e["workflow_id"]
            for e in tracker.get_active(user_id="u1", accessible_project_ids={"p1"})
        }
        assert "wf-live" in reported, "a workflow inside its budget must still be reported"
        assert "wf-lost" not in reported, (
            "a workflow older than every job budget is still reported as running: its "
            "entry is removed only by a matching `pipeline_end`, so one lost Redis "
            "message pins it to `/api/tasks/active` for ever (COR-08)"
        )

    def test_the_age_ceiling_follows_the_job_budgets(self) -> None:
        """A constant here would go stale the moment a budget moves."""
        from app.config import settings
        from app.core.workflow_tracker import WorkflowTracker

        ceiling = WorkflowTracker()._active_max_age_seconds()
        assert ceiling > settings.repo_index_job_timeout_seconds, (
            f"the ceiling ({ceiling}s) is at or below the longest job budget "
            f"({settings.repo_index_job_timeout_seconds}s), so a full repo index "
            "would be dropped from the active map while it is still running"
        )


class TestTheContextMeterMeasuresTheConversation:
    """COR-04.

    The endpoint reported `history_budget_remaining = max_history_tokens` — the
    constant, unconditionally — and computed utilization from the size of the SCHEMA,
    rules and learnings, none of which change while a conversation runs. So a bar the
    UI paints red above 80% read the same number on a user's thousandth message as on
    their first, and `rotation_imminent` shared no variable with the trigger:
    `chat.py` compares stored history against `max_context_tokens *
    session_rotation_threshold_pct / 100`, while the meter used `max_history_tokens`
    — 2 500 against 32 000, not even the same constant.
    """

    def test_the_meter_and_the_trigger_read_the_same_threshold(self) -> None:
        from app.config import settings
        from app.core.session_rotation import rotation_threshold_tokens

        expected = int(settings.max_context_tokens * settings.session_rotation_threshold_pct / 100)
        assert rotation_threshold_tokens() == expected

    def test_utilization_moves_with_the_conversation(self) -> None:
        from app.core.session_rotation import measure

        empty = measure([])
        busy = measure(["x" * 40_000, "y" * 40_000])
        assert empty.utilization_pct < busy.utilization_pct, (
            "the meter must move as history accumulates — the whole defect was a "
            "figure computed from the static context, which cannot (COR-04)"
        )

    def test_imminent_predicts_the_thing_that_actually_rotates(self) -> None:
        from app.core.session_rotation import IMMINENT_FRACTION, HistoryPressure

        threshold = 8000
        just_under = HistoryPressure(
            history_tokens=int(threshold * IMMINENT_FRACTION) + 1,
            threshold_tokens=threshold,
            rotation_enabled=True,
        )
        assert just_under.imminent and not just_under.should_rotate

        over = HistoryPressure(
            history_tokens=threshold + 1, threshold_tokens=threshold, rotation_enabled=True
        )
        assert over.should_rotate, "past the threshold is not a prediction, it is the event"
        assert not over.imminent

        early = HistoryPressure(
            history_tokens=10, threshold_tokens=threshold, rotation_enabled=True
        )
        assert not early.imminent

    def test_the_trigger_asks_the_shared_helper(self) -> None:
        """A meter that merely MATCHES the trigger is one refactor from lying again."""
        source = (_BACKEND / "app" / "api" / "routes" / "chat.py").read_text(encoding="utf-8")
        assert "measure_history_pressure(" in source, (
            "`/ask/stream` computes the rotation decision itself again; the estimate "
            "endpoint then predicts a different number (COR-04)"
        )

    def test_the_endpoint_takes_the_session_it_claims_to_measure(self) -> None:
        from app.api.routes.chat_utility import estimate_cost

        assert "session_id" in inspect.signature(estimate_cost).parameters, (
            "the endpoint reported a history figure for a session it was never told about (COR-04)"
        )


class TestADegradedAnswerSpeaksTheUsersLanguage:
    """COR-05."""

    async def test_a_static_fallback_is_translated(self) -> None:
        from app.agents.localize import localize

        class _Router:
            def __init__(self) -> None:
                self.calls: list[Any] = []

            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                self.calls.append(messages)
                return SimpleNamespace(content="Достигнут предел шагов анализа.")

        router = _Router()
        out = await localize(
            "I reached the maximum number of analysis steps.",
            "сколько заказов было в июле?",
            router,
        )
        assert out == "Достигнут предел шагов анализа."
        assert router.calls, "nothing was asked"

    async def test_it_can_only_ever_return_the_original(self) -> None:
        """This runs where something already failed. It must not add a second failure."""
        from app.agents.localize import localize

        english = "I reached the processing time limit."

        class _Raises:
            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                raise RuntimeError("token budget exhausted")

        class _Rambles:
            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                return SimpleNamespace(content="Sure! " + "very long answer " * 60)

        class _Empty:
            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                return SimpleNamespace(content="   ")

        class _NotText:
            """A provider whose `content` is not a string — found by a Mock doing it."""

            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                return SimpleNamespace(content=object())

        for router in (_Raises(), _Rambles(), _Empty(), _NotText(), None):
            assert await localize(english, "сколько?", router) == english

    async def test_no_question_means_no_call(self) -> None:
        from app.agents.localize import localize

        class _Counting:
            calls = 0

            async def complete(self, messages, **kw):  # noqa: ANN001, ANN003
                type(self).calls += 1
                return SimpleNamespace(content="x")

        router = _Counting()
        assert await localize("English text", None, router) == "English text"
        assert router.calls == 0, "a call with nothing to detect the language from"

    def test_every_static_answer_path_goes_through_it(self) -> None:
        """Discovered from the source: a new fallback cannot quietly stay English."""
        source = (_BACKEND / "app" / "agents" / "orchestrator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        unlocalized: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target = ast.unparse(node.targets[0]) if node.targets else ""
            if target != "final_text":
                continue
            value = ast.unparse(node.value)
            builds_static = "build_partial_text" in value or "build_timeout_text" in value
            if builds_static and "_localize_static" not in value:
                unlocalized.append(f"line {node.lineno}: {value[:80]}")
        assert not unlocalized, (
            f"{unlocalized} assign a hardcoded English fallback as the answer body. "
            "README promises the language rule at 'step-limit/emergency synthesis', "
            "and these are exactly the paths with no LLM to apply it (COR-05)"
        )
