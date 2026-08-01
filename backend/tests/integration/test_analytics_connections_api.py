"""Integration tests for the analytics half of /api/connections (spec §5, T9).

Four things are load-bearing here and each has a test whose failure mode is a
real user-visible bug, not a signature check:

1. **No fabricated database.** A GA4 connection must persist with no engine, no
   port, no database name and — the one that actually bit us — no
   ``127.0.0.1`` host. A plausible-looking placeholder is worse than a null:
   every downstream guard that asks "is this a database?" answers yes.
2. **The credential is owner-strict.** Referencing another tenant's vendor
   credential is refused *and* the refusal is a 404, not a 500 — a stack trace
   would leak that the id exists.
3. **A caveat is not an error.** The journal records a ``degraded`` sentence in
   ``error`` on an otherwise ``ok`` row (truncated vendor page). The status
   endpoint has to surface that as a caveat; rendering it as a failure would
   make a successful collection look broken.
4. **Database connections are untouched.** The regression test on ``to_config``
   is the most important one in the file: every existing connection in
   production flows through it.

The shared ``auth_client`` fixture is used deliberately (not a hand-built app):
these routes only work if the connections router is actually mounted in
``app.main``. Every seeded row is committed and then re-asserted before the
behaviour under test runs, so nothing here can pass because a write vanished.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import journal
from app.config import settings
from app.models.analytics_ga4 import GA4OverviewDaily
from app.models.analytics_import import AnalyticsImport
from app.models.connection import Connection
from app.models.vendor_credential import VendorCredential
from tests.integration.conftest import auth_headers, register_user

GA4_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIBT9SECRETGA4\n-----END PRIVATE KEY-----\n"
GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "demo-project",
        "client_email": "collector@demo-project.iam.gserviceaccount.com",
        "private_key": GA4_PRIVATE_KEY,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

SOURCE_CONFIG: dict[str, Any] = {
    "property_ids": ["294380179"],
    "backfill_days": 3,
    "event_names": ["pin_show_promo"],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _expected_days(backfill_days: int) -> list[str]:
    """The periods the collect window covers, oldest first — ends *yesterday*.

    Mirrors ``analytics_collect_service.period_range`` in the scheduler's
    timezone so the test and the endpoint agree on what "pending" means.
    """
    today = dt.datetime.now(ZoneInfo(settings.daily_knowledge_sync_timezone)).date()
    end = today - dt.timedelta(days=1)
    return [
        (end - dt.timedelta(days=offset)).isoformat() for offset in range(backfill_days - 1, -1, -1)
    ]


async def _create_project(
    client: AsyncClient, headers: dict[str, str] | None = None, name: str = "GA4 Proj"
) -> str:
    resp = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_credential(
    client: AsyncClient,
    headers: dict[str, str] | None = None,
    *,
    provider: str = "ga4",
    name: str = "ga4-sa",
    secret: str = GA4_SECRET,
) -> str:
    resp = await client.post(
        "/api/vendor-credentials",
        headers=headers,
        json={"name": name, "provider": provider, "secret": secret},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _ga4_payload(project_id: str, credential_id: str | None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "name": "Marketing GA4",
        "source_type": "ga4",
        "vendor_credential_id": credential_id,
        "source_config": SOURCE_CONFIG,
        "collection_enabled": True,
        "collection_hour": 4,
    }
    payload.update(overrides)
    return payload


async def _connection_count(db_session: AsyncSession, project_id: str) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(Connection).where(Connection.project_id == project_id)
    )
    return int(result.scalar_one())


@pytest_asyncio.fixture()
async def ga4_conn(auth_client: AsyncClient, db_session: AsyncSession):
    """A committed GA4 connection + its credential. Returns (connection_id, credential_id)."""
    headers = dict(auth_client.headers)
    pid = await _create_project(auth_client, headers)
    cred_id = await _create_credential(auth_client, headers)
    resp = await auth_client.post("/api/connections", json=_ga4_payload(pid, cred_id))
    assert resp.status_code == 200, resp.text
    yield resp.json()["id"], cred_id


# ---------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------


class TestCreateAnalyticsConnection:
    async def test_ga4_connection_persists_without_any_database_fields(
        self, auth_client: AsyncClient, db_session: AsyncSession
    ):
        pid = await _create_project(auth_client)
        cred_id = await _create_credential(auth_client)

        resp = await auth_client.post("/api/connections", json=_ga4_payload(pid, cred_id))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["source_type"] == "ga4"
        assert body["db_type"] is None
        assert body["db_port"] is None
        assert body["db_name"] is None
        assert not body["db_host"], f"db_host was back-filled with {body['db_host']!r}"
        assert body["vendor_credential_id"] == cred_id
        assert body["source_config"] == SOURCE_CONFIG
        assert body["collection_enabled"] is True
        assert body["collection_hour"] == 4

        row = await db_session.get(Connection, body["id"])
        assert row is not None, "connection was not committed"
        # The stored row, not just the serialisation: a placeholder here would
        # make every "is this a database?" guard answer yes.
        assert row.db_type is None
        assert row.db_port is None
        assert row.db_name is None
        assert row.db_host in (None, "")
        assert row.db_host != "127.0.0.1"
        assert json.loads(row.source_config_json or "{}") == SOURCE_CONFIG

    async def test_analytics_connection_requires_a_credential(self, auth_client: AsyncClient):
        pid = await _create_project(auth_client)
        resp = await auth_client.post("/api/connections", json=_ga4_payload(pid, None))
        assert resp.status_code == 422, resp.text
        assert "credential" in resp.text.lower()

    async def test_credential_owned_by_another_user_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner_a = await register_user(client, db_session=db_session)
        owner_b = await register_user(client, db_session=db_session)
        headers_a = auth_headers(owner_a["token"])
        headers_b = auth_headers(owner_b["token"])

        cred_a = await _create_credential(client, headers_a, name="a-cred")
        pid_b = await _create_project(client, headers_b, name="B Proj")

        # Precondition: the credential really exists and really belongs to A —
        # otherwise a 404 below would pass for the wrong reason.
        cred_row = await db_session.get(VendorCredential, cred_a)
        assert cred_row is not None and cred_row.user_id == owner_a["user_id"]
        before = await _connection_count(db_session, pid_b)

        resp = await client.post(
            "/api/connections", json=_ga4_payload(pid_b, cred_a), headers=headers_b
        )
        assert resp.status_code in (403, 404), resp.text
        assert resp.status_code != 500
        assert await _connection_count(db_session, pid_b) == before

    async def test_credential_provider_must_match_source_type(
        self, auth_client: AsyncClient, db_session: AsyncSession
    ):
        pid = await _create_project(auth_client)
        headers = dict(auth_client.headers)
        wrong = await _create_credential(
            auth_client, headers, provider="appstore", name="p8", secret="-----BEGIN PRIVATE KEY--"
        )

        cred_row = await db_session.get(VendorCredential, wrong)
        assert cred_row is not None and cred_row.provider == "appstore"
        before = await _connection_count(db_session, pid)

        resp = await auth_client.post("/api/connections", json=_ga4_payload(pid, wrong))
        assert resp.status_code == 422, resp.text
        assert "appstore" in resp.text
        assert await _connection_count(db_session, pid) == before

    async def test_collection_hour_out_of_range_is_rejected(self, auth_client: AsyncClient):
        pid = await _create_project(auth_client)
        cred_id = await _create_credential(auth_client)
        resp = await auth_client.post(
            "/api/connections", json=_ga4_payload(pid, cred_id, collection_hour=24)
        )
        assert resp.status_code == 422, resp.text

    async def test_database_connection_still_creates_with_its_defaults(
        self, auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Regression: the analytics branch must not touch the database path."""
        pid = await _create_project(auth_client)
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Prod PG",
                "db_type": "postgres",
                "db_host": "db.internal",
                "db_port": 5432,
                "db_name": "shop",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_type"] == "database"
        assert (body["db_type"], body["db_host"], body["db_port"], body["db_name"]) == (
            "postgres",
            "db.internal",
            5432,
            "shop",
        )
        assert body["vendor_credential_id"] is None

        row = await db_session.get(Connection, body["id"])
        assert row is not None
        assert (row.db_type, row.db_host, row.db_port, row.db_name) == (
            "postgres",
            "db.internal",
            5432,
            "shop",
        )


class TestUpdateAnalyticsConnection:
    async def test_patch_updates_collection_knobs_without_db_fields(
        self, auth_client: AsyncClient, db_session: AsyncSession, ga4_conn
    ):
        cid, _ = ga4_conn
        resp = await auth_client.patch(
            f"/api/connections/{cid}",
            json={
                "collection_enabled": False,
                "collection_hour": 21,
                "source_config": {"property_ids": ["999"], "backfill_days": 7},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["collection_enabled"] is False
        assert body["collection_hour"] == 21
        assert body["source_config"] == {"property_ids": ["999"], "backfill_days": 7}

        row = await db_session.get(Connection, cid)
        assert row is not None
        await db_session.refresh(row)
        assert row.collection_enabled is False
        assert row.collection_hour == 21
        assert row.db_host in (None, "")
        assert json.loads(row.source_config_json or "{}")["backfill_days"] == 7

    async def test_patch_rejects_another_users_credential(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner_a = await register_user(client, db_session=db_session)
        owner_b = await register_user(client, db_session=db_session)
        headers_a = auth_headers(owner_a["token"])
        headers_b = auth_headers(owner_b["token"])

        cred_a = await _create_credential(client, headers_a, name="a-only")
        pid_b = await _create_project(client, headers_b, name="B Proj 2")
        cred_b = await _create_credential(client, headers_b, name="b-cred")
        created = await client.post(
            "/api/connections", json=_ga4_payload(pid_b, cred_b), headers=headers_b
        )
        assert created.status_code == 200, created.text
        cid = created.json()["id"]

        resp = await client.patch(
            f"/api/connections/{cid}", json={"vendor_credential_id": cred_a}, headers=headers_b
        )
        assert resp.status_code in (403, 404), resp.text

        row = await db_session.get(Connection, cid)
        assert row is not None and row.vendor_credential_id == cred_b


# ---------------------------------------------------------------------------
# to_config
# ---------------------------------------------------------------------------


class TestToConfig:
    async def test_ga4_config_carries_knobs_and_the_decrypted_secret(
        self, db_session: AsyncSession, ga4_conn
    ):
        from app.analytics.ga4.config import CREDENTIAL_SECRET_KEY, SOURCE_CONFIG_KEY
        from app.services.connection_service import ConnectionService

        cid, _ = ga4_conn
        conn = await db_session.get(Connection, cid)
        assert conn is not None

        config = await ConnectionService().to_config(db_session, conn)

        assert config.db_type == "ga4"
        assert config.db_host == ""
        assert config.db_port == 0
        assert config.db_name == ""
        assert config.extra[SOURCE_CONFIG_KEY] == SOURCE_CONFIG
        assert config.extra[CREDENTIAL_SECRET_KEY] == GA4_SECRET
        # …and the adapter can actually read it back.
        from app.analytics.ga4.config import GA4Config

        assert GA4Config.from_connection_config(config).property_ids == ("294380179",)

    async def test_database_config_is_unchanged(
        self, auth_client: AsyncClient, db_session: AsyncSession
    ):
        """The regression that matters most: every existing connection uses this."""
        from app.services.connection_service import ConnectionService

        pid = await _create_project(auth_client)
        resp = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "Legacy PG",
                "db_type": "postgres",
                "db_host": "db.internal",
                "db_port": 6543,
                "db_name": "shop",
                "db_user": "reader",
                "db_password": "s3cret",
                "is_read_only": True,
            },
        )
        assert resp.status_code == 200, resp.text
        conn = await db_session.get(Connection, resp.json()["id"])
        assert conn is not None

        config = await ConnectionService().to_config(db_session, conn)

        assert config.db_type == "postgres"
        assert config.db_host == "db.internal"
        assert config.db_port == 6543
        assert config.db_name == "shop"
        assert config.db_user == "reader"
        assert config.db_password == "s3cret"
        assert config.is_read_only is True
        assert config.connection_id == conn.id
        assert config.extra == {}


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


class TestCollectNow:
    async def test_collect_enqueues_exactly_one_job(
        self, auth_client: AsyncClient, monkeypatch, ga4_conn
    ):
        from app.core import task_queue

        cid, _ = ga4_conn
        calls: list[tuple[str, dict[str, Any]]] = []

        async def _fake_enqueue(task_name: str, coro_factory=None, **kwargs: Any):
            calls.append((task_name, {"coro_factory": coro_factory, **kwargs}))
            return kwargs.get("task_id")

        monkeypatch.setattr(task_queue, "enqueue", _fake_enqueue)

        resp = await auth_client.post(f"/api/connections/{cid}/collect")
        assert resp.status_code == 202, resp.text

        assert len(calls) == 1
        name, kwargs = calls[0]
        assert name == "run_analytics_collect"
        assert kwargs["connection_id"] == cid
        assert kwargs["task_id"].startswith(f"analytics_collect:{cid}:")
        assert kwargs["_job_timeout"] == settings.analytics_collect_job_timeout_seconds
        assert resp.json()["task_id"] == kwargs["task_id"]

        # The fallback coroutine must actually collect this connection.
        collected: list[str] = []

        class _FakeService:
            async def collect(self, connection_id: str):
                collected.append(connection_id)

        monkeypatch.setattr(
            "app.services.analytics_collect_service.AnalyticsCollectService", _FakeService
        )
        await kwargs["coro_factory"]()
        assert collected == [cid]

    async def test_collect_works_on_a_paused_connection(
        self, auth_client: AsyncClient, monkeypatch, ga4_conn
    ):
        """`collection_enabled=False` pauses the *cron*, not "collect now"."""
        from app.core import task_queue

        cid, _ = ga4_conn
        patched = await auth_client.patch(
            f"/api/connections/{cid}", json={"collection_enabled": False}
        )
        assert patched.status_code == 200 and patched.json()["collection_enabled"] is False

        calls: list[str] = []

        async def _fake_enqueue(task_name: str, coro_factory=None, **kwargs: Any):
            calls.append(task_name)
            return "job"

        monkeypatch.setattr(task_queue, "enqueue", _fake_enqueue)
        resp = await auth_client.post(f"/api/connections/{cid}/collect")
        assert resp.status_code == 202, resp.text
        assert calls == ["run_analytics_collect"]

    async def test_collect_on_a_database_connection_is_400(
        self, auth_client: AsyncClient, monkeypatch
    ):
        from app.core import task_queue

        calls: list[str] = []

        async def _fake_enqueue(task_name: str, coro_factory=None, **kwargs: Any):
            calls.append(task_name)
            return "job"

        monkeypatch.setattr(task_queue, "enqueue", _fake_enqueue)

        pid = await _create_project(auth_client)
        created = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "PG",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "shop",
            },
        )
        cid = created.json()["id"]

        resp = await auth_client.post(f"/api/connections/{cid}/collect")
        assert resp.status_code == 400, resp.text
        assert "analytics" in resp.json()["detail"].lower()
        assert calls == []

    async def test_collect_on_missing_connection_is_404(self, auth_client: AsyncClient):
        resp = await auth_client.post("/api/connections/does-not-exist/collect")
        assert resp.status_code == 404


class TestDatabaseOnlyRoutesRejectAnalytics:
    """Schema/code routes must refuse a GA4 source instead of dispatching a
    pipeline that cannot succeed and leaves a run row stuck in ``running``."""

    async def test_index_db_is_400(self, auth_client: AsyncClient, ga4_conn):
        cid, _ = ga4_conn
        resp = await auth_client.post(f"/api/connections/{cid}/index-db")
        assert resp.status_code == 400, resp.text
        assert "collect" in resp.json()["detail"]

    async def test_sync_is_400(self, auth_client: AsyncClient, ga4_conn):
        cid, _ = ga4_conn
        resp = await auth_client.post(f"/api/connections/{cid}/sync")
        assert resp.status_code == 400, resp.text
        assert "collect" in resp.json()["detail"]

    async def test_refresh_schema_is_400(self, auth_client: AsyncClient, ga4_conn):
        cid, _ = ga4_conn
        resp = await auth_client.post(f"/api/connections/{cid}/refresh-schema")
        assert resp.status_code == 400, resp.text
        assert "Google Analytics 4" in resp.json()["detail"]


class TestTestConnection:
    async def test_bad_ga4_credential_fails_honestly_instead_of_500(
        self, auth_client: AsyncClient, ga4_conn
    ):
        """The fixture's service-account key is syntactically valid but fake.

        Building google-auth credentials from it fails locally — no network, no
        vendor call — and the route must turn that into an honest
        ``success: False`` with a readable reason, never a 500.
        """
        cid, _ = ga4_conn
        resp = await auth_client.post(f"/api/connections/{cid}/test")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert body["error"]
        # The failure is reported, not swallowed into a bogus auto-index.
        assert "auto_indexing" not in body
        # …and the secret never appears in the message.
        assert "MIIBT9SECRETGA4" not in resp.text


# ---------------------------------------------------------------------------
# collection-status
# ---------------------------------------------------------------------------


class TestCollectionStatus:
    async def test_reports_latest_ok_pending_and_treats_degraded_as_a_caveat(
        self, auth_client: AsyncClient, db_session: AsyncSession, ga4_conn
    ):
        cid, _ = ga4_conn
        days = _expected_days(SOURCE_CONFIG["backfill_days"])
        assert len(days) == 3

        # overview: two collected, the newest day still owed.
        await journal.record(
            db_session,
            connection_id=cid,
            report="overview",
            period=days[0],
            status="ok",
            rows_written=10,
        )
        await journal.record(
            db_session,
            connection_id=cid,
            report="overview",
            period=days[1],
            status="ok",
            rows_written=12,
        )
        # geo: collected, but the vendor capped the page — an `ok` row that
        # carries a caveat in `error`.
        await journal.record(
            db_session,
            connection_id=cid,
            report="geo",
            period=days[2],
            status="ok",
            rows_written=250_000,
            error="GA4 returned more rows than the cap; data is partial",
        )
        # events: a real failure.
        await journal.record(
            db_session,
            connection_id=cid,
            report="events",
            period=days[0],
            status="failed",
            error="quota exhausted",
        )

        seeded = await db_session.execute(
            select(func.count())
            .select_from(AnalyticsImport)
            .where(AnalyticsImport.connection_id == cid)
        )
        assert int(seeded.scalar_one()) == 4, "journal seeding did not commit"

        resp = await auth_client.get(f"/api/connections/{cid}/collection-status")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["connection_id"] == cid
        assert body["source_type"] == "ga4"
        assert body["collection_enabled"] is True
        assert body["next_scheduled_hour"] == 4
        assert body["status"] == "partial"
        assert body["last_error"] == "quota exhausted"

        by_report = {r["report"]: r for r in body["reports"]}
        assert set(by_report) >= {"overview", "geo", "platform", "trend", "events"}

        overview = by_report["overview"]
        assert overview["latest_ok_period"] == days[1]
        assert overview["ok_periods"] == 2
        assert overview["pending_periods"] == 1
        assert overview["pending_sample"] == [days[2]]
        assert overview["last_error"] is None
        assert overview["caveat"] is None

        geo = by_report["geo"]
        assert geo["latest_ok_period"] == days[2]
        # The caveat is a caveat — not an error.
        assert geo["last_error"] is None
        assert "partial" in (geo["caveat"] or "")
        assert geo["pending_periods"] == 2

        events = by_report["events"]
        assert events["latest_ok_period"] is None
        assert events["failed_periods"] == 1
        assert events["last_error"] == "quota exhausted"
        # A failed period stays owed — the hole below the watermark refills.
        assert events["pending_periods"] == 3
        assert days[0] in events["pending_sample"]

        # A never-touched report is "not collected", not "collected as zero".
        platform = by_report["platform"]
        assert platform["latest_ok_period"] is None
        assert platform["ok_periods"] == 0
        assert platform["pending_periods"] == 3

    async def test_genuinely_empty_periods_are_not_reported_as_failures(
        self, auth_client: AsyncClient, db_session: AsyncSession, ga4_conn
    ):
        """`empty` is a completed period, not a broken one (spec §2.4)."""
        cid, _ = ga4_conn
        days = _expected_days(SOURCE_CONFIG["backfill_days"])
        for day in days:
            await journal.record(
                db_session, connection_id=cid, report="overview", period=day, status="empty"
            )

        seeded = await db_session.execute(
            select(func.count())
            .select_from(AnalyticsImport)
            .where(AnalyticsImport.connection_id == cid, AnalyticsImport.status == "empty")
        )
        assert int(seeded.scalar_one()) == len(days), "journal seeding did not commit"

        body = (await auth_client.get(f"/api/connections/{cid}/collection-status")).json()
        assert body["status"] != "failed"
        assert body["last_error"] is None

        overview = next(r for r in body["reports"] if r["report"] == "overview")
        assert overview["empty_periods"] == len(days)
        assert overview["failed_periods"] == 0
        # An empty period is done — it is never refetched forever.
        assert overview["pending_periods"] == 0
        assert overview["latest_ok_period"] is None
        assert overview["latest_collected_period"] == days[-1]

    async def test_never_collected_connection_says_so(self, auth_client: AsyncClient, ga4_conn):
        cid, _ = ga4_conn
        resp = await auth_client.get(f"/api/connections/{cid}/collection-status")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "never_collected"
        assert body["last_run_at"] is None
        assert body["last_error"] is None
        assert all(r["latest_ok_period"] is None for r in body["reports"])

    async def test_status_on_a_database_connection_is_400(self, auth_client: AsyncClient):
        pid = await _create_project(auth_client)
        created = await auth_client.post(
            "/api/connections",
            json={
                "project_id": pid,
                "name": "PG",
                "db_type": "postgres",
                "db_host": "127.0.0.1",
                "db_name": "shop",
            },
        )
        cid = created.json()["id"]
        resp = await auth_client.get(f"/api/connections/{cid}/collection-status")
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------


class TestDeleteCascade:
    async def test_deleting_the_connection_removes_journal_and_fact_rows(
        self, auth_client: AsyncClient, db_session: AsyncSession, ga4_conn
    ):
        cid, _ = ga4_conn
        await journal.record(
            db_session,
            connection_id=cid,
            report="overview",
            period="2026-07-30",
            status="ok",
            rows_written=1,
        )
        db_session.add(
            GA4OverviewDaily(
                id=str(uuid.uuid4()),
                connection_id=cid,
                property_id="294380179",
                date=dt.date(2026, 7, 30),
                sessions=12,
                active_users=7,
                new_users=3,
                screen_page_views=40,
                event_count=99,
            )
        )
        await db_session.commit()

        async def _counts() -> tuple[int, int]:
            j = await db_session.execute(
                select(func.count())
                .select_from(AnalyticsImport)
                .where(AnalyticsImport.connection_id == cid)
            )
            f = await db_session.execute(
                select(func.count())
                .select_from(GA4OverviewDaily)
                .where(GA4OverviewDaily.connection_id == cid)
            )
            return int(j.scalar_one()), int(f.scalar_one())

        # Precondition — without this the assertion below passes on an empty table.
        assert await _counts() == (1, 1)

        resp = await auth_client.delete(f"/api/connections/{cid}")
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        assert await _counts() == (0, 0)
