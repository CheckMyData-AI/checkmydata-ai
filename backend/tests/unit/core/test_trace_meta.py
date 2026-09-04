"""A trace that cannot be finished without saying how it was routed (Ш0 · REQ-1/2/3).

`finalize_trace` accepted `route`/`complexity`/`estimated_queries`/`failure_kind`
as keyword arguments with defaults, and **zero of its twelve call sites passed
any of them** — so production carried `route = "unknown"` in 222 traces out of
222 while the documentation claimed the opposite.

The default is the defect. These tests pin the replacement: a required record,
one constructor per kind of run, and no way to be vague by accident.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.trace_meta import PRICE_SOURCES, UNKNOWN, TraceMeta


class TestFromResponse:
    def test_it_reads_the_routing_the_agent_took(self):
        resp = SimpleNamespace(route="explore", complexity="complex", estimated_queries=3)
        meta = TraceMeta.from_response(resp)
        assert (meta.route, meta.complexity, meta.estimated_queries) == ("explore", "complex", 3)

    def test_a_missing_field_degrades_rather_than_raises(self):
        """A trace is worth writing even when one of its facts is absent."""
        meta = TraceMeta.from_response(SimpleNamespace())
        assert meta.route == UNKNOWN
        assert meta.complexity == UNKNOWN
        assert meta.estimated_queries == 0

    def test_an_empty_string_is_unknown_not_empty(self):
        """`route=""` in a column is indistinguishable from a bug. `unknown` is a value."""
        meta = TraceMeta.from_response(SimpleNamespace(route="", complexity=None))
        assert meta.route == UNKNOWN and meta.complexity == UNKNOWN

    def test_an_explicit_failure_kind_overrides_the_response(self):
        resp = SimpleNamespace(route="explore", failure_kind="transient")
        assert TraceMeta.from_response(resp, failure_kind="fatal").failure_kind == "fatal"

    def test_the_failure_kind_is_normalised_through_the_one_vocabulary(self):
        resp = SimpleNamespace(route="explore", failure_kind="  TRANSIENT ")
        assert TraceMeta.from_response(resp).failure_kind == "transient"
        assert TraceMeta.from_response(SimpleNamespace(failure_kind="nonsense")).failure_kind == (
            "fatal"
        )


class TestAborted:
    def test_routing_stays_unknown_and_that_is_the_truth(self):
        """On a timeout the router may not have run at all."""
        meta = TraceMeta.aborted("transient")
        assert meta.route == UNKNOWN
        assert meta.failure_kind == "transient"

    def test_a_failure_kind_is_required(self):
        with pytest.raises(ValueError, match="requires a failure kind"):
            TraceMeta.aborted("")

    def test_an_unknown_kind_still_records_a_failure(self):
        assert TraceMeta.aborted("provider exploded").failure_kind == "fatal"


class TestUtility:
    def test_it_separates_no_router_from_nobody_wired_the_router(self):
        """The single "unknown" value could not tell these apart, and the whole
        point of Ш0 is being able to ask which one a row is."""
        assert TraceMeta.utility().route == "utility"
        assert TraceMeta.from_response(SimpleNamespace()).route == UNKNOWN

    def test_a_named_route_is_kept(self):
        assert TraceMeta.utility("generate_title").route == "generate_title"

    def test_a_clean_utility_run_has_no_failure_kind(self):
        assert TraceMeta.utility().failure_kind is None


class TestCostCarriesItsProvenance:
    def test_no_price_means_source_none_and_that_is_not_zero(self):
        meta = TraceMeta.utility()
        assert meta.cost_usd is None and meta.price_source == "none"

    def test_a_cost_must_name_where_its_price_came_from(self):
        """The same number means different things from a live price and a
        snapshot, so a cost without provenance cannot be audited."""
        with pytest.raises(ValueError, match="claims a price produced a cost"):
            TraceMeta(cost_usd=None, price_source="shared_cache")

    def test_an_unknown_price_source_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="unknown price_source"):
            TraceMeta(cost_usd=0.5, price_source="vibes")

    def test_with_cost_returns_a_copy_and_never_mutates(self):
        base = TraceMeta.from_response(SimpleNamespace(route="explore"))
        priced = base.with_cost(0.42, "shared_cache")
        assert priced.cost_usd == 0.42 and priced.price_source == "shared_cache"
        assert base.cost_usd is None, "the original record must be untouched"
        assert priced.route == "explore", "the routing must survive the copy"

    def test_every_declared_source_constructs(self):
        for src in PRICE_SOURCES:
            cost = None if src == "none" else 0.1
            assert TraceMeta(cost_usd=cost, price_source=src).price_source == src


class TestItIsARecordNotAScratchpad:
    def test_it_is_frozen(self):
        meta = TraceMeta.utility()
        with pytest.raises(FrozenInstanceError):
            meta.route = "explore"  # type: ignore[misc]


class TestNothingHeavyIsImported:
    def test_only_stdlib_and_the_failure_kind_vocabulary(self):
        """Imported by the orchestrator, the chat routes, the MCP server and the
        trace service. A record that drags in SQLAlchemy cannot be reached from
        all four, and the second copy gets written instead."""
        src = Path(inspect.getfile(TraceMeta)).read_text(encoding="utf-8")
        app_imports: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                app_imports.add(node.module)
        assert app_imports == {"app.core.failure_kind"}, (
            f"trace_meta may only import the failure-kind vocabulary; found {app_imports}"
        )


class TestFinalizeTraceCannotBeCalledWithoutIt:
    def test_meta_is_a_required_keyword(self):
        """The whole defect was a default. A parameter with one is a parameter
        twelve call sites can and did ignore."""
        from app.services.trace_persistence_service import TracePersistenceService

        sig = inspect.signature(TracePersistenceService.finalize_trace)
        param = sig.parameters.get("meta")
        assert param is not None, "finalize_trace must take a TraceMeta"
        assert param.default is inspect.Parameter.empty, (
            "meta must have NO default — a default is what let 12 of 12 call "
            "sites omit the routing for 222 traces"
        )

    def test_the_loose_routing_kwargs_are_gone(self):
        """Leaving them beside `meta` would let a caller set one and not the
        other, and nothing would say which won."""
        from app.services.trace_persistence_service import TracePersistenceService

        sig = inspect.signature(TracePersistenceService.finalize_trace)
        for gone in ("route", "complexity", "estimated_queries", "failure_kind"):
            assert gone not in sig.parameters, (
                f"{gone} must now travel inside TraceMeta, not as a loose kwarg"
            )

    def test_every_call_site_passes_meta(self):
        """The structural guard. A thirteenth entry point added later without
        `meta=` fails here rather than in production six weeks on."""
        roots = [
            "app/api/routes/chat.py",
            "app/api/routes/chat_utility.py",
            "app/api/routes/chat_sessions.py",
            "app/mcp_server/tools.py",
        ]
        missing: list[str] = []
        for path in roots:
            src = Path(path).read_text(encoding="utf-8")
            idx = src.find("finalize_trace(")
            while idx != -1:
                open_paren = idx + len("finalize_trace(") - 1
                depth, end = 0, None
                for j in range(open_paren, min(len(src), open_paren + 4000)):
                    if src[j] == "(":
                        depth += 1
                    elif src[j] == ")":
                        depth -= 1
                        if depth == 0:
                            end = j
                            break
                call = src[idx : end if end is not None else open_paren + 4000]
                if "meta=" not in call:
                    missing.append(f"{path}:{src[:idx].count(chr(10)) + 1}")
                idx = src.find("finalize_trace(", idx + 1)

        assert not missing, f"finalize_trace called without meta= at: {missing}"
