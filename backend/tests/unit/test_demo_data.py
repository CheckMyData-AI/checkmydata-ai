"""The demo's sample database — the part of `/api/demo/setup` that can be tested pure.

F-EXP-01. SCN-003 promises the demo path "sets up sample data" and the button offers to
load it; the route seeded nothing and pointed at `:memory:`, which is empty on every
fresh connection regardless of what any single connection wrote. A first-run user saw an
empty database.

These tests exercise `_seed_demo_db` directly — they open the file it wrote and read the
rows back, rather than asserting that the word "INSERT" appears somewhere in the module.
That distinction is the finding: the 2026-07-19 audit passed SCN-003 by checking the
button and the toasts, which are affordances, not the promise.
"""

from __future__ import annotations

import sqlite3

from app.config import settings
from app.services.demo_data import (
    demo_db_path,
    is_demo_db,
    repair_demo_db_if_missing,
    seed_demo_db,
)


def _rows(path, sql: str) -> list[tuple]:
    with sqlite3.connect(path) as db:
        return db.execute(sql).fetchall()


class TestTheSampleDataExists:
    def test_seeding_creates_the_tables_and_fills_them(self, tmp_path):
        path = tmp_path / "demo.db"
        seed_demo_db(path)

        assert _rows(path, "SELECT COUNT(*) FROM customers")[0][0] > 0
        assert _rows(path, "SELECT COUNT(*) FROM orders")[0][0] > 0

    def test_the_data_answers_a_question_a_demo_user_would_ask(self, tmp_path):
        """A join across both tables must return rows, or the demo shows one table twice."""
        path = tmp_path / "demo.db"
        seed_demo_db(path)

        revenue = _rows(
            path,
            "SELECT c.country, SUM(o.total_cents) FROM orders o "
            "JOIN customers c ON c.id = o.customer_id "
            "WHERE o.status = 'paid' GROUP BY c.country",
        )
        assert revenue, "the sample data has no paid orders to aggregate"
        assert all(total > 0 for _, total in revenue)

    def test_every_order_points_at_a_customer_that_exists(self, tmp_path):
        """A dangling FK in sample data teaches the agent a schema the demo contradicts."""
        path = tmp_path / "demo.db"
        seed_demo_db(path)

        orphans = _rows(
            path,
            "SELECT COUNT(*) FROM orders o "
            "WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = o.customer_id)",
        )
        assert orphans[0][0] == 0


class TestSeedingTwiceIsSafe:
    def test_a_second_call_does_not_duplicate_the_rows(self, tmp_path):
        """The route re-seeds on every call, because the dyno filesystem is ephemeral and
        a missing file is indistinguishable from a first visit. That only works if a
        second call over a populated file is a no-op."""
        path = tmp_path / "demo.db"
        seed_demo_db(path)
        first = _rows(path, "SELECT COUNT(*) FROM customers")[0][0]

        seed_demo_db(path)

        assert _rows(path, "SELECT COUNT(*) FROM customers")[0][0] == first

    def test_a_deleted_file_is_seeded_again(self, tmp_path):
        """Heroku's filesystem does not survive a restart, and the project row does. If
        re-seeding needed a fresh project, the user's second visit would be the empty
        database all over again."""
        path = tmp_path / "demo.db"
        seed_demo_db(path)
        path.unlink()

        seed_demo_db(path)

        assert _rows(path, "SELECT COUNT(*) FROM customers")[0][0] > 0


class TestRepairIsScopedToTheDemo:
    """`repair_demo_db_if_missing` runs inside `ConnectionService.to_config`, which every
    query, index and health check passes through. Writing sample tables into a database
    it does not own would be a data-integrity incident, so containment is the contract."""

    def test_a_missing_demo_file_is_rebuilt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        path = demo_db_path("user-1")
        seed_demo_db(path)
        path.unlink()

        repair_demo_db_if_missing(str(path))

        assert path.exists()
        assert _rows(path, "SELECT COUNT(*) FROM customers")[0][0] > 0

    def test_an_existing_demo_file_is_left_alone(self, tmp_path, monkeypatch):
        """Idempotent, and cheap: a `COUNT(*)` over five rows on every config build."""
        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        path = demo_db_path("user-1")
        seed_demo_db(path)
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM orders WHERE id = 1")
        before = _rows(path, "SELECT COUNT(*) FROM orders")[0][0]

        repair_demo_db_if_missing(str(path))

        assert _rows(path, "SELECT COUNT(*) FROM orders")[0][0] == before

    def test_a_users_own_database_is_never_touched(self, tmp_path, monkeypatch):
        """The check is directory containment, not a filename pattern: a user's SQLite
        file called `demo_anything.db` outside the managed directory is theirs."""
        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        theirs = tmp_path / "elsewhere" / "demo_user-1.db"
        theirs.parent.mkdir(parents=True)

        assert is_demo_db(str(theirs)) is False
        repair_demo_db_if_missing(str(theirs))

        assert not theirs.exists(), "a database outside the demo directory was created"

    def test_no_path_is_not_a_demo(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        assert is_demo_db(None) is False
        assert is_demo_db("") is False
        repair_demo_db_if_missing(None)  # must not raise

    def test_a_repair_failure_does_not_propagate(self, tmp_path, monkeypatch):
        """`to_config` builds configs for every connection in the product. A demo file
        that cannot be written must not stop an unrelated connection being opened — the
        connector's own error is the honest one to show."""
        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        path = demo_db_path("user-1")

        def _boom(*_a, **_k):
            raise OSError("disk is full")

        monkeypatch.setattr("app.services.demo_data.seed_demo_db", _boom)
        repair_demo_db_if_missing(str(path))  # must not raise


class TestTheDemoDatabaseIsQueryableThroughTheProduct:
    async def test_the_seeded_file_answers_a_query_through_the_connector(
        self, tmp_path, monkeypatch
    ):
        """The seam the four board findings sat on: `db_type="sqlite"` had no adapter, so
        a seeded file was still a connection the product could not open."""
        from app.connectors.base import ConnectionConfig
        from app.connectors.registry import get_connector

        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        path = demo_db_path("user-1")
        seed_demo_db(path)

        connector = get_connector("sqlite")
        await connector.connect(
            ConnectionConfig(db_type="sqlite", db_name=str(path), is_read_only=True)
        )
        result = await connector.execute_query(
            "SELECT c.country, SUM(o.total_cents) FROM orders o "
            "JOIN customers c ON c.id = o.customer_id "
            "WHERE o.status = 'paid' GROUP BY c.country ORDER BY 2 DESC"
        )

        assert result.error is None
        assert result.columns[0] == "country"
        assert result.rows, "the demo's own sample data returned nothing"


class TestTheRepairIsActuallyWired:
    """A tested helper nobody calls is a tested helper nobody calls.

    Measured: deleting `repair_demo_db_if_missing(db_name)` from
    `ConnectionService.to_config` left every test above green — the helper's own suite
    cannot see whether the product uses it. That is the same shape as the source-grep
    tests this change already deleted, one layer up.
    """

    async def test_to_config_rebuilds_a_missing_demo_database(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock

        from app.models.connection import Connection
        from app.services.connection_service import ConnectionService

        monkeypatch.setattr(settings, "demo_db_dir", str(tmp_path / "demo"))
        path = demo_db_path("user-1")
        seed_demo_db(path)
        path.unlink()

        conn = Connection(
            id="c1",
            project_id="p1",
            name="Demo SQLite",
            db_type="sqlite",
            db_host="",
            db_port=0,
            db_name=str(path),
            is_read_only=True,
        )
        config = await ConnectionService().to_config(AsyncMock(), conn)

        assert config.db_name == str(path)
        assert path.exists(), "to_config did not rebuild the demo database"
        assert _rows(path, "SELECT COUNT(*) FROM customers")[0][0] > 0
