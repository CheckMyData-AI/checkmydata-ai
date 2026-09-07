"""What the data workspace needs the API to say, and what it must never let it guess.

`SCR-01` renders one card per source, and each card states what the agent can actually
DO with that source. Two ways to build that, and only one of them survives contact with
this codebase:

* the card derives it from `db_type` and `source_type` — which is `is_queryable_database`
  reimplemented in TypeScript, in a language that cannot import it, drifting the first
  time a vendor is added;
* the API says it.

The second, because the first has already gone wrong here once: a caller that derived
SQL availability from "is a connection attached?" advertised `query_database` for a GA4
source, and `get_connector("ga4")` then raised in the middle of the user's chat.

`SCN-132`, `SCN-147`.
"""

from __future__ import annotations

import re

import pytest

from app.api.routes.connections import capability_of


class TestTheCardIsToldWhatASourceIs:
    @pytest.mark.parametrize("db_type", ["postgres", "mysql", "clickhouse", "mongodb", "mcp"])
    def test_an_engine_is_queryable(self, db_type: str) -> None:
        assert capability_of(db_type=db_type, source_type="database") == "queryable"

    @pytest.mark.parametrize("vendor", ["ga4", "appstore", "googleplay"])
    def test_an_analytics_source_is_collected_not_queryable(self, vendor: str) -> None:
        """The card must never offer to query one of these. `db_type` carries the VENDOR
        id for an analytics source because that is what the adapter dispatches on, so a
        naive reading of it says "queryable" and is wrong."""
        assert capability_of(db_type=vendor, source_type=vendor) == "collected"

    def test_a_source_with_no_engine_is_unknown_not_queryable(self) -> None:
        """Unknown is a real answer and it links to Test. Defaulting to queryable is how
        the model gets handed a tool that raises."""
        assert capability_of(db_type=None, source_type="database") == "unknown"

    def test_the_vendor_family_is_read_not_restated(self) -> None:
        """One home for the list. A second copy is a second thing to update when a
        vendor is added, and the one nobody remembers."""
        import inspect

        from app.api.routes import connections

        src = inspect.getsource(connections.capability_of)
        assert "ANALYTICS_SOURCE_TYPES" in src or "is_analytics_source" in src
        # Read the CODE, not the prose. The docstring names ga4 as the example the
        # rule exists for, and a guard that punishes explaining itself gets the
        # explanation deleted — the same lesson as the scheduled-wave guard.
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))
        assert '"ga4"' not in code, "the vendor ids must not be spelled out here"

    def test_the_response_carries_it_as_something_nobody_can_set(self) -> None:
        """A computed property, not a field: it must not be populatable from the source
        object. A plain field with an `after` validator still gets READ from attributes
        first, so any object that answers to every attribute supplies a bad value that is
        rejected before the validator can fix it."""
        from app.api.routes.connections import ConnectionResponse

        assert "capability" in ConnectionResponse.model_computed_fields
        assert "capability" not in ConnectionResponse.model_fields


class TestTheScheduleSaysWhetherItMayRun:
    """`SCN-147`: the absence of automation must be visible where the automation would
    have been. The control cannot render its own reason without being told."""

    def test_the_schedule_endpoint_reports_it(self) -> None:
        import inspect

        from app.api.routes import projects

        src = inspect.getsource(projects.get_sync_schedule)
        assert "may_run" in src
        assert "may_run_scheduled_work" in src

    def test_it_asks_the_registry_not_the_commercial_service(self) -> None:
        """Asking `EntitlementService()` directly would tell every self-hosted build its
        schedule cannot run — the registry is what keeps that provider out of that build."""
        import inspect

        from app.api.routes import projects

        src = inspect.getsource(projects.get_sync_schedule)
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
        assert "EntitlementService(" not in code
