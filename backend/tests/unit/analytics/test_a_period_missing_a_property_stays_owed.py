"""A-01: a period one property failed in is not finished.

`fetch` unions every configured property, and the 2026-09-03 isolation fix made one
property's failure survivable — the surviving rows are returned with a `degraded`
sentence. The journal then recorded `ok`, which is a **done** status: the missing
property's data was permanently absent outside the two-period refetch tail, and the tail
then overwrote the note that said so. The agent, reading the caveat, called it "the
vendor truncated this period" — a different cause, and the wrong one.
"""

from __future__ import annotations

from app.analytics.base import AnalyticsReport
from app.analytics.journal import DONE_STATUSES, VALID_STATUSES


def test_partial_is_a_status_and_is_not_done():
    assert "partial" in VALID_STATUSES
    assert "partial" not in DONE_STATUSES, (
        "a done status is what made the missing property permanent"
    )


def test_a_report_says_whether_a_source_was_missing():
    complete = AnalyticsReport(columns=["a"], rows=[[1]])
    assert complete.incomplete is False

    partial = AnalyticsReport(columns=["a"], rows=[[1]], incomplete=True, degraded="property 2 …")
    assert partial.incomplete is True


def test_a_truncated_report_is_not_an_incomplete_one():
    """Different facts: a cap means more rows exist; incomplete means a source is absent."""
    capped = AnalyticsReport(columns=["a"], rows=[[1]], truncated=True)
    assert capped.incomplete is False


def test_the_adapter_marks_a_missing_property():
    import inspect

    from app.analytics.ga4 import adapter

    source = inspect.getsource(adapter.GA4Adapter.fetch)
    assert "incomplete=bool(failures)" in source


def test_the_collect_service_writes_partial_for_it():
    import inspect

    from app.services.analytics_collect_service import AnalyticsCollectService

    source = inspect.getsource(AnalyticsCollectService)
    assert 'status="partial" if fetched.incomplete else "ok"' in source, (
        "the rows are kept and the period stays pending — that is the whole fix"
    )
