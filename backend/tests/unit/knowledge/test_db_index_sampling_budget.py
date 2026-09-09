"""Sampling a customer's live database must be bounded, and it was not.

Measured on production, `db_index` runs with `trigger='auto'`, all of them `completed`
and all of them ending at the `fetch_samples` step:

    2026-08-13   30 279 s   (8 h 25 m)
    2026-08-19   23 198 s   (6 h 27 m)
    2026-08-06    8 793 s
    2026-08-03    8 593 s

The same 213 tables under `trigger='schedule'` average **1 544 s**. Nothing in the step
bounds it: `fetch_samples` is one `asyncio.gather` over every table, each doing a sample
query plus up to `db_index_stats_max_columns` distinct-value queries plus approximate
statistics — against the customer's own database, often through an SSH tunnel.

**Who starts an `auto` run, established 2026-09-09 and worth stating because it changes
what those eight hours were.** Three paths reach `trigger="auto"`, all through
`_ensure_db_index_wf` (`connections.py:70`):

* `FreshnessReconciler` (`main.py:821`), when the index is older than
  `db_index_ttl_hours` — but `freshness_reconciler_enabled` defaults to `False` and is
  **not set on production**, so this path has never run there;
* `POST /connections/{id}/test` (`connections.py:915`);
* `POST /connections/{id}/refresh-schema` (`connections.py:1012`, only for connections
  that already have an index).

So on production every one of those runs was started by **a person pressing a button**,
and what they saw was an operation that never came back. The manual `/index-db` route
mints its own run and is `trigger='manual'`, which is why it never appeared in this list.

The budget below does not make sampling faster. It makes the step *finish*: a table
without statistics is a known gap the prompt can work around, and eight hours against a
production database is not.
"""

from __future__ import annotations

import pytest

from app.knowledge.db_index_pipeline import SamplingBudget


class TestTheBudgetStops:
    def test_a_fresh_budget_is_not_exhausted(self) -> None:
        assert not SamplingBudget(seconds=60).exhausted()

    def test_it_reports_exhaustion_once_the_window_is_spent(self) -> None:
        b = SamplingBudget(seconds=60)
        b._deadline = b._now() - 1.0  # spend it, without sleeping through a minute
        assert b.exhausted()

    def test_a_skipped_table_is_named_not_merely_counted(self) -> None:
        """The August runs left no table name in the log at all, which is why nobody
        could say what those eight hours were spent on. A count would repeat that."""
        b = SamplingBudget(seconds=60)
        b.skip("orders")
        b.skip("payments")
        assert b.skipped == ["orders", "payments"]
        assert "orders" in b.summary() and "payments" in b.summary()

    def test_the_summary_is_printed_on_a_clean_run_too(self) -> None:
        """Silence is not a passing check. A run that sampled everything must still say
        so, or an operator cannot tell a complete run from one whose logging broke."""
        b = SamplingBudget(seconds=60)
        b.record("orders", 0.4)
        b.record("users", 0.2)
        s = b.summary()
        assert "2 table(s)" in s
        assert "skipped" not in s.lower() or "0" in s

    def test_the_summary_names_the_slowest_table(self) -> None:
        b = SamplingBudget(seconds=60)
        b.record("small", 0.1)
        b.record("enormous", 91.5)
        b.record("medium", 3.0)
        s = b.summary()
        assert "enormous" in s, (
            "the summary must name what took the time; a total alone leaves the next "
            "eight-hour run as unexplainable as the last one"
        )

    def test_only_slow_tables_are_worth_a_line_of_their_own(self) -> None:
        """213 tables at one line each is noise that hides the four that matter."""
        b = SamplingBudget(seconds=60)
        assert not b.is_noteworthy(0.9)
        assert b.is_noteworthy(SamplingBudget.SLOW_TABLE_SECONDS + 0.1)

    def test_a_budget_of_zero_is_refused_by_construction(self) -> None:
        """Symmetry with the config validator: a bound that means "never sample" is not
        a bound, and neither is one that means "sample forever"."""
        with pytest.raises(ValueError):
            SamplingBudget(seconds=0)
        with pytest.raises(ValueError):
            SamplingBudget(seconds=-1)


class TestTheConfigRefusesAnUnboundedStep:
    def test_the_default_is_positive_and_documented(self) -> None:
        from app.config import settings

        assert settings.db_index_fetch_samples_budget_seconds > 0

    @pytest.mark.parametrize("bad", [0, -1, -1800])
    def test_a_non_positive_budget_raises_at_boot(self, bad: int) -> None:
        """Not clamped. A `0` that reads as configured and behaves as absent is how the
        step came to be unbounded in the first place."""
        from app.config import Settings

        with pytest.raises(ValueError, match="DB_INDEX_FETCH_SAMPLES_BUDGET_SECONDS"):
            Settings(db_index_fetch_samples_budget_seconds=bad)


class TestTheStepHonoursTheBudget:
    """The class above is the bookkeeping; this is that the step consults it.

    `fetch_samples` lives inside a 600-line method that a unit test cannot reach without
    a live connector, a tracker and a session, so these are source-level. They pin the
    three decisions that make the difference between a bound and a decoration.
    """

    def _step_source(self) -> str:
        import inspect
        import re

        from app.knowledge import db_index_pipeline

        src = inspect.getsource(db_index_pipeline)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))

    def test_the_step_builds_a_budget_from_the_setting(self) -> None:
        body = " ".join(self._step_source().split())
        assert "SamplingBudget(settings.db_index_fetch_samples_budget_seconds)" in body, (
            "the step does not build a budget, so the setting is decoration"
        )

    def test_a_queued_table_gives_up_rather_than_piling_up(self) -> None:
        body = self._step_source()
        assert "_budget.exhausted()" in body, "nothing checks the budget"
        assert "_budget.skip(table.name)" in body, (
            "a table dropped for the budget must be named; the August runs left no table "
            "name in the log at all, which is why those eight hours are still unexplained"
        )

    def test_the_check_happens_after_the_semaphore_not_before(self) -> None:
        """A table already holding a slot is mid-query against the customer's database;
        cancelling it buys nothing. What the budget stops is the queue behind it."""
        body = self._step_source()
        acquire = body.index("async with _sample_sem:")
        check = body.index("_budget.exhausted()")
        assert acquire < check, (
            "the budget is checked before the semaphore, which would abandon tables that "
            "never got a chance to run rather than the ones still waiting"
        )

    def test_the_summary_is_unconditional_and_the_warning_is_not(self) -> None:
        body = self._step_source()
        assert "logger.info(_budget.summary())" in body, (
            "the summary must print on a clean run too — silence is not a passing check"
        )
        assert "if _budget.skipped:" in body, (
            "the warning must be conditional on something actually having been skipped"
        )

    def test_a_skipped_table_looks_like_one_with_no_evidence(self) -> None:
        """Not a third state. Downstream already branches on "no sample for this table";
        inventing `skipped` would need a new branch at every reader, and the ones that
        were missed would silently treat absence as zero."""
        body = " ".join(self._step_source().split())
        assert "QueryResult(columns=[], rows=[], row_count=0)" in body
