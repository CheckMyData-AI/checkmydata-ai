"""A-11 and A-12: a project's quota is the project's, and a new source is visible at once.

**A-11** — `tokens_per_project_per_hour` is spent across every property in the Google
Cloud project, and GA4 reports it on each property's response. Recording it under the
property that observed it left every other property spending vendor calls that could
only be refused.

**A-12** — "does this project have an analytics source" was cached for 60 s and nothing
cleared it, so adding a GA4 connection and asking a question inside that minute got an
agent with no analytics tool, and deleting one got a tool with nothing behind it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.analytics.errors import QuotaExhaustedError
from app.analytics.ga4.adapter import GA4Adapter, _is_project_bucket


def _quota(bucket: str, *, consumed: int = 25_000, remaining: int = 0):
    return SimpleNamespace(**{bucket: SimpleNamespace(consumed=consumed, remaining=remaining)})


def test_the_project_buckets_are_named():
    assert _is_project_bucket("tokens_per_project_per_hour")
    assert not _is_project_bucket("tokens_per_day")
    assert not _is_project_bucket("concurrent_requests")


def test_a_spent_project_bucket_stops_every_property():
    adapter = GA4Adapter()

    adapter._note_quota("111", _quota("tokens_per_project_per_hour"))

    assert adapter._project_quota_exhausted == "tokens_per_project_per_hour"
    assert adapter._quota_exhausted == {}, "it is not the observing property's problem alone"


def test_a_spent_property_bucket_stops_only_that_property():
    adapter = GA4Adapter()

    adapter._note_quota("111", _quota("tokens_per_day"))

    assert adapter._quota_exhausted == {"111": "tokens_per_day"}
    assert adapter._project_quota_exhausted is None


def test_an_unpopulated_bucket_is_not_exhaustion():
    adapter = GA4Adapter()

    adapter._note_quota("111", _quota("tokens_per_project_per_hour", consumed=0, remaining=0))

    assert adapter._project_quota_exhausted is None, "an all-zero proto default is not a verdict"


@pytest.mark.asyncio
async def test_the_next_call_for_another_property_is_refused():
    from unittest.mock import MagicMock

    adapter = GA4Adapter()
    # `_run_report` asks for the client before anything else; the refusal must come
    # before the vendor call, not instead of a connection.
    adapter._client = MagicMock()
    adapter._config = SimpleNamespace(property_ids=["222"])
    adapter._project_quota_exhausted = "tokens_per_project_per_hour"

    with pytest.raises(QuotaExhaustedError, match="project-wide"):
        await adapter._run_report(SimpleNamespace(property="properties/222"))


def test_the_capability_cache_can_be_cleared():
    from app.agents.context_loader import _ANALYTICS_CACHE, invalidate_capability_cache

    _ANALYTICS_CACHE["proj-1"] = (False, 0.0)
    invalidate_capability_cache("proj-1")

    assert "proj-1" not in _ANALYTICS_CACHE
    invalidate_capability_cache("proj-1")  # idempotent: a project with nothing cached


def test_every_route_that_changes_what_a_project_has_clears_it():
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3] / "app" / "api" / "routes" / "connections.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in ("create_connection", "update_connection", "delete_connection"):
        fn = next(
            n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name
        )
        assert "invalidate_capability_cache" in ast.dump(fn), (
            f"{name} changes what the project has and must say so"
        )
