"""A-02 and A-03: a revoked key stops the run, and a GA4 source is not a database.

**A-02** — the token refresh happens inside gRPC's metadata plugin, so a revoked or
deleted service-account key comes back as `InternalServerError`: HTTP 500, which the
status mapping reads as "the vendor is having a moment". Three attempts per period,
about 450 doomed refreshes per run, nightly, for ever — and because it never becomes an
auth error the report is never stopped and the `_connect` sentinel is never written, so
nothing says the key is gone.

**A-03** — the nightly sync's `_active_connections` filtered on `is_active` alone, so it
ran the DB-index pipeline against GA4 connections: the vendor secret was decrypted for
nothing, `get_connector("ga4")` raised "Unsupported adapter", and the analytics row was
left `indexing_status=failed` — a red badge on a source whose collection had worked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analytics.errors import AnalyticsAuthError, AnalyticsTransientError
from app.analytics.ga4.adapter import GA4Adapter, _is_auth_failure, _map_client_error


def test_a_refresh_error_is_an_auth_failure_however_it_arrives():
    from google.auth.exceptions import RefreshError

    direct = RefreshError("invalid_grant: account not found")
    assert _is_auth_failure(direct)

    wrapped = RuntimeError("Getting metadata from plugin failed with error: invalid_grant")
    assert _is_auth_failure(wrapped), "gRPC's own wording must be recognised"

    chained = RuntimeError("internal")
    chained.__cause__ = RefreshError("invalid_grant")
    assert _is_auth_failure(chained), "the cause chain is where the truth usually is"


def test_an_ordinary_server_error_is_still_transient():
    assert not _is_auth_failure(RuntimeError("503 Service Unavailable"))


def test_a_five_hundred_that_is_really_a_dead_key_is_classified_auth():
    exc = RuntimeError("500 Getting metadata from plugin failed with error: invalid_grant")
    exc.code = 500  # type: ignore[attr-defined]

    mapped = _map_client_error(exc)

    assert isinstance(mapped, AnalyticsAuthError), (
        "retried as transient, this costs ~450 token refreshes a night and says nothing"
    )


def test_a_real_five_hundred_stays_transient():
    exc = RuntimeError("500 Internal error encountered")
    exc.code = 500  # type: ignore[attr-defined]

    assert isinstance(_map_client_error(exc), AnalyticsTransientError)


@pytest.mark.asyncio
class TestTheProbeRefreshesTheToken:
    def _adapter(self, refresh_error: Exception | None):
        adapter = GA4Adapter()
        adapter._config = SimpleNamespace(property_ids=["123"])
        # `_require_config` asks for both: an adapter with no client is "not connected"
        # and would never reach the refresh.
        adapter._client = MagicMock()
        creds = MagicMock()
        built = MagicMock()
        if refresh_error is not None:
            built.refresh.side_effect = refresh_error
        creds.build_credentials.return_value = built
        adapter._credentials = creds
        return adapter, built

    async def test_a_revoked_key_fails_the_probe(self):
        from google.auth.exceptions import RefreshError

        adapter, built = self._adapter(RefreshError("invalid_grant: account not found"))

        assert await adapter.test_connection() is False
        assert built.refresh.called, "a report request cannot tell a dead key from a hiccup"

    async def test_a_live_key_reaches_the_report(self):
        adapter, built = self._adapter(None)
        with patch.object(GA4Adapter, "_run_report", new=AsyncMock(return_value=MagicMock())):
            with patch.object(GA4Adapter, "_build_request", return_value=MagicMock()):
                assert await adapter.test_connection() is True
        assert built.refresh.called


def test_the_nightly_sync_leaves_analytics_sources_alone():
    """A-03, structurally: the filter asks what the connection IS, not only whether it is on."""
    import inspect

    from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService

    source = inspect.getsource(DailyKnowledgeSyncService._active_connections)
    assert "is_analytics_source" in source, (
        "a GA4 row has no database to index; the pipeline answered 'Unsupported adapter' "
        "and marked the row failed every night"
    )
