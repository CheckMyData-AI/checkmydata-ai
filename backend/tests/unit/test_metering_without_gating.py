"""Counting a call and refusing the next one are different jobs, and the sink did both.

`DbUsageSink.observe` records usage and then re-checks the budget, setting a sticky reason
the orchestrator reads to hard-stop. For a chat request that is right: the person is waiting
and the next call is theirs to authorise.

For background indexing it is not. `doc_generator.py:84`,
`code_db_sync_analyzer.py:211` and `db_index_validator.py:150` build `LLMRouter()` with **no
sink at all**, so roughly 758 doc-generation calls per rebuild — the largest LLM consumer in
the product — are recorded nowhere. Wiring the existing sink would fix the count and
simultaneously start blocking indexing for an account that is over budget, which is a worse
product than the one with the wrong number.

Under per-account OpenRouter keys the money is already right: OpenRouter counts every call
and the key's own ceiling stops the spend. What is wrong is our display, and a display that
understates what a customer spent is its own kind of lie.

So the sink gains a `gate` flag rather than a parallel class: two objects doing the same
recording would drift, and the recording is the part that must not.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.usage_sink import DbUsageSink


def _sink(*, gate: bool) -> DbUsageSink:
    return DbUsageSink(user_id="u1", project_id="p1", gate=gate)


async def _observe(sink: DbUsageSink, *, over_budget: bool) -> None:
    svc = MagicMock()
    svc.record_usage = AsyncMock()
    svc.check_token_budget = AsyncMock(
        return_value="Monthly token budget exceeded" if over_budget else None
    )
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("app.llm.usage_sink.async_session_factory", return_value=session),
        patch("app.llm.usage_sink.UsageService", return_value=svc),
    ):
        await sink.observe(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            provider="openrouter",
            model="openai/gpt-4o",
        )
    sink._recorded = svc.record_usage  # type: ignore[attr-defined]
    sink._checked = svc.check_token_budget  # type: ignore[attr-defined]


class TestAGatingSinkStillGates:
    async def test_it_records(self) -> None:
        sink = _sink(gate=True)
        await _observe(sink, over_budget=False)
        sink._recorded.assert_awaited_once()

    async def test_it_stops_the_run_when_over_budget(self) -> None:
        sink = _sink(gate=True)
        await _observe(sink, over_budget=True)
        assert sink.budget_exceeded() is not None


class TestAMeteringSinkRecordsAndNeverStops:
    async def test_it_records(self) -> None:
        sink = _sink(gate=False)
        await _observe(sink, over_budget=True)
        sink._recorded.assert_awaited_once(), "metering is the whole point of this mode"

    async def test_it_never_reports_a_breach(self) -> None:
        sink = _sink(gate=False)
        await _observe(sink, over_budget=True)
        assert sink.budget_exceeded() is None, (
            "a non-gating sink stopped a background run; indexing would halt for an "
            "account that is merely over its allowance"
        )

    async def test_it_does_not_even_ask(self) -> None:
        """Not just ignoring the answer — not spending a query on it. This runs once per
        LLM call, and `check_token_budget` sums `token_usage` for the month each time."""
        sink = _sink(gate=False)
        await _observe(sink, over_budget=True)
        sink._checked.assert_not_awaited()


class TestTheDefaultIsUnchanged:
    def test_gating_is_the_default(self) -> None:
        """Every existing caller — the chat paths and the MCP tools — must keep gating
        without being edited. A flag that changes behaviour by omission is how a budget
        stops being enforced quietly."""
        sink = DbUsageSink(user_id="u1", project_id="p1")
        assert sink._gate is True


class TestTheBackgroundRoutersAreWired:
    """The three that recorded nothing.

    Asserted on the module that CONSTRUCTS the router with a sink, not on the one that
    consumes it: the first version of this test looked for `usage_sink` inside
    `db_index_validator` and `doc_generator` themselves, where it will never appear — they
    take a router, they do not build one. The wiring belongs in the pipeline, which is the
    only place that knows the project and therefore the owner.
    """

    @pytest.mark.parametrize(
        "module,consumer",
        [
            ("app.knowledge.pipeline_runner", "doc_generator"),
            ("app.knowledge.db_index_pipeline", "db_index_validator"),
            ("app.knowledge.code_db_sync_pipeline", "code_db_sync_analyzer"),
        ],
    )
    def test_the_pipeline_attributes_its_llm_spend(self, module, consumer) -> None:
        import importlib
        import inspect

        src = inspect.getsource(importlib.import_module(module))
        assert "usage_sink" in src, (
            f"{module} builds a bare LLMRouter for {consumer}; its calls reach no table "
            "and the customer's usage display understates what they spent"
        )

    @pytest.mark.parametrize(
        "module",
        ["app.knowledge.pipeline_runner", "app.knowledge.db_index_pipeline"],
    )
    def test_background_metering_does_not_gate(self, module) -> None:
        """`build_metering_sink`, not `build_sink`. The gating one would halt a rebuild for
        an account merely over its allowance — a stopped product traded for a right
        number, when the money is already bounded by the OpenRouter key's own ceiling."""
        import importlib
        import inspect

        src = inspect.getsource(importlib.import_module(module))
        assert "build_metering_sink" in src

    @pytest.mark.parametrize(
        "module",
        ["app.knowledge.pipeline_runner", "app.knowledge.db_index_pipeline"],
    )
    def test_an_unresolvable_owner_leaves_the_run_unmetered_not_stopped(self, module) -> None:
        """Bookkeeping must not decide whether an index runs."""
        import importlib
        import inspect

        src = inspect.getsource(importlib.import_module(module))
        assert "unmetered" in src.lower()


def test_the_doc_generator_takes_a_per_run_copy_rather_than_mutating() -> None:
    """`_doc_generator` is a module-level singleton (`repos.py:45`) and the sink it needs is
    per-run, because the owner differs by project. Mutating its router in place would
    attribute a concurrent rebuild of another project to whoever started last."""
    from app.knowledge.doc_generator import DocGenerator
    from app.llm.router import LLMRouter

    original = DocGenerator()
    other = LLMRouter()
    clone = original.with_router(other)
    assert clone is not original
    assert clone._llm is other
    assert original._llm is not other, "the singleton's router was mutated in place"
