"""A-05 and A-09: one run per connection, and an empty refetch removes what it replaced.

**A-05** — `POST /connections/{id}/collect` (ten a minute, its own task id since ANA-10)
and the hourly wave could run one connection at the same time, each spending the
property's full daily quota on the same periods, with interleaved sweep `DELETE`s
between them. The route's docstring claimed the task id prevented it; that had stopped
being true when the ids were separated.

**A-09** — the sweep that removes rows a vendor has revised away lives inside `_upsert`,
which an empty fetch never reaches. A period refetched as empty kept its old rows, and
they went on counting into totals published as real measurements.
"""

from __future__ import annotations

import inspect

from app.services.analytics_collect_service import AnalyticsCollectService


def test_a_second_collection_of_one_connection_is_refused():
    source = inspect.getsource(AnalyticsCollectService.collect)
    assert "redis_lock" in source and "analytics:collect:" in source
    assert "already being collected" in source


def test_the_lock_outlives_the_job_it_guards():
    from app.config import settings
    from app.services.analytics_collect_service import _COLLECT_LOCK_TTL_SECONDS

    # A lock that expires mid-run is worse than none: the second caller starts while the
    # first is still writing, which is the interleaving this exists to prevent.
    assert _COLLECT_LOCK_TTL_SECONDS > settings.analytics_collect_job_timeout_seconds


def test_the_route_no_longer_claims_the_task_id_prevents_a_race():
    from app.api.routes import connections as routes

    doc = inspect.getdoc(routes.collect_now) or ""
    assert "never race" not in doc
    assert "already being collected" in doc or "per-connection lock" in doc


def test_an_empty_refetch_deletes_that_period():
    """On the parse tree: the delete must sit in the EMPTY handler, not merely exist.

    A first version of this test looked for the method's name anywhere in the class and
    passed with the call site removed — the method was still defined, and defining it is
    not what makes the stale rows go.
    """
    import ast
    from pathlib import Path

    source = Path(inspect.getfile(AnalyticsCollectService)).read_text(encoding="utf-8")
    handlers = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ExceptHandler)
        and "AnalyticsEmpty" in ast.dump(node.type or ast.Pass())
    ]
    assert handlers, "the empty-fetch path is where a revised-away period is noticed"
    assert any("_delete_period_rows" in ast.dump(h) for h in handlers), (
        "an empty refetch left its old rows counting into published totals"
    )

    body = inspect.getsource(AnalyticsCollectService._delete_period_rows)
    assert "connection_id" in body and "date_column >= first" in body, (
        "the delete must be scoped to one connection and one period"
    )
