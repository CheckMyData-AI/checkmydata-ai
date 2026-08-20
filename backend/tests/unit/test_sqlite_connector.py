"""The SQLite connector — the demo's connection could never be opened without it.

`app/api/routes/demo.py` has created `db_type="sqlite"` connections since the demo path
existed, and `ADAPTER_REGISTRY` had no entry for it, so `get_adapter` raised
`ValueError: Unsupported adapter: sqlite` the first time a new user asked a question.
Seeding the sample data (F-EXP-01) does not close that on its own: a database nobody can
connect to is the same empty screen with more work behind it.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.config import settings
from app.connectors.base import ConnectionConfig
from app.connectors.registry import get_adapter, get_connector
from app.connectors.sqlite import SQLiteConnector


@pytest.fixture
def managed_dir(tmp_path, monkeypatch):
    """SQLite connections are confined to the demo directory (see the connector's
    docstring): a filename on the server's own disk is both "which database" and "which
    file may this process read"."""
    directory = tmp_path / "demo"
    directory.mkdir()
    monkeypatch.setattr(settings, "demo_db_dir", str(directory))
    return directory


@pytest.fixture
def db_file(managed_dir):
    path = managed_dir / "sample.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                total_cents INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX idx_customer_name ON customers(name);
            CREATE VIEW paid_totals AS SELECT customer_id, SUM(total_cents) t FROM orders
                GROUP BY customer_id;
            INSERT INTO customers VALUES (1, 'Aurora', 'DE'), (2, 'Bluefin', 'GB');
            INSERT INTO orders VALUES (1, 1, 1000), (2, 2, 2500);
            """
        )
    return path


async def _connected(path, *, read_only: bool = True) -> SQLiteConnector:
    conn = SQLiteConnector()
    await conn.connect(
        ConnectionConfig(db_type="sqlite", db_name=str(path), is_read_only=read_only)
    )
    return conn


class TestItIsReachableAtAll:
    def test_the_registry_resolves_sqlite(self):
        """The finding, in one line: this raised `ValueError: Unsupported adapter`."""
        assert isinstance(get_adapter("database", "sqlite"), SQLiteConnector)
        assert isinstance(get_connector("sqlite"), SQLiteConnector)


class TestQuerying:
    async def test_a_select_returns_columns_and_rows(self, db_file):
        conn = await _connected(db_file)
        result = await conn.execute_query("SELECT id, name FROM customers ORDER BY id")

        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.rows == [[1, "Aurora"], [2, "Bluefin"]]
        assert result.row_count == 2

    async def test_a_join_across_tables_works(self, db_file):
        conn = await _connected(db_file)
        result = await conn.execute_query(
            "SELECT c.country, SUM(o.total_cents) FROM orders o "
            "JOIN customers c ON c.id = o.customer_id GROUP BY c.country ORDER BY c.country"
        )

        assert result.rows == [["DE", 1000], ["GB", 2500]]

    async def test_parameters_are_bound_not_interpolated(self, db_file):
        conn = await _connected(db_file)
        result = await conn.execute_query(
            "SELECT name FROM customers WHERE country = :c", {"c": "GB"}
        )

        assert result.rows == [["Bluefin"]]

    async def test_a_bad_query_returns_an_error_rather_than_raising(self, db_file):
        conn = await _connected(db_file)
        result = await conn.execute_query("SELECT * FROM nope")

        assert result.error
        assert result.rows == []

    async def test_querying_before_connect_says_so(self):
        result = await SQLiteConnector().execute_query("SELECT 1")
        assert result.error == "Not connected"


class TestReadOnlyIsEnforcedByTheDriver:
    async def test_a_write_is_refused_on_a_read_only_connection(self, db_file):
        """vision.md §7 #1. `SafetyGuard`'s allow-list runs above this; neither layer is
        the whole answer, which is why the other four connectors also push the guarantee
        into the engine."""
        conn = await _connected(db_file, read_only=True)

        result = await conn.execute_query("INSERT INTO customers VALUES (3, 'Cedar', 'US')")

        assert result.error, "a read-only connection accepted a write"
        with sqlite3.connect(db_file) as db:
            assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 2

    async def test_a_writable_connection_still_writes(self, db_file):
        """The read-only guarantee has to come from the mode, not from the connector
        being incapable — otherwise the test above proves nothing."""
        conn = await _connected(db_file, read_only=False)

        result = await conn.execute_query("INSERT INTO customers VALUES (3, 'Cedar', 'US')")

        assert result.error is None
        with sqlite3.connect(db_file) as db:
            assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 3


class TestConnectRefusesWhatCannotWork:
    async def test_in_memory_is_refused(self):
        """`:memory:` is a different empty database per connection, so seeding it in one
        shows nothing in the next — it reads as configured and behaves as empty. That is
        F-EXP-01's exact shape, and it was the demo's configured target."""
        with pytest.raises(ValueError, match="memory"):
            await SQLiteConnector().connect(ConnectionConfig(db_type="sqlite", db_name=":memory:"))

    async def test_a_path_outside_the_demo_directory_is_refused(self, managed_dir, tmp_path):
        """The escalation this connector would otherwise open. `ConnectionUpdate.db_name`
        and `db_type` are free strings, so a user who clicks the demo could repoint their
        connection at `./data/agent.db` — the application's own database, holding every
        tenant's rows and encrypted credentials — and ask a question about it."""
        app_db = tmp_path / "agent.db"
        app_db.write_bytes(b"")

        with pytest.raises(ValueError, match="outside"):
            await SQLiteConnector().connect(ConnectionConfig(db_type="sqlite", db_name=str(app_db)))

    async def test_traversal_out_of_the_demo_directory_is_refused(self, managed_dir, tmp_path):
        """`demo/../agent.db` is inside the directory as a string and outside it as a
        file, which is why the check resolves before it compares."""
        (tmp_path / "agent.db").write_bytes(b"")
        traversal = str(managed_dir / ".." / "agent.db")

        with pytest.raises(ValueError, match="outside"):
            await SQLiteConnector().connect(ConnectionConfig(db_type="sqlite", db_name=traversal))

    async def test_a_symlink_pointing_out_is_refused(self, managed_dir, tmp_path):
        """Resolution covers symlinks for the same reason it covers `..`."""
        outside = tmp_path / "agent.db"
        outside.write_bytes(b"")
        link = managed_dir / "innocent.db"
        link.symlink_to(outside)

        with pytest.raises(ValueError, match="outside"):
            await SQLiteConnector().connect(ConnectionConfig(db_type="sqlite", db_name=str(link)))

    async def test_an_empty_path_is_refused(self):
        with pytest.raises(ValueError, match="db_name"):
            await SQLiteConnector().connect(ConnectionConfig(db_type="sqlite", db_name=""))

    async def test_a_missing_file_is_refused_rather_than_created(self, managed_dir):
        """sqlite3 creates the file on a plain path, so a typo'd path would otherwise
        look exactly like a working connection over a database with no tables."""
        missing = managed_dir / "not-here.db"

        with pytest.raises(FileNotFoundError):
            await SQLiteConnector().connect(
                ConnectionConfig(db_type="sqlite", db_name=str(missing), is_read_only=True)
            )

        assert not missing.exists()


class TestIntrospection:
    async def test_tables_columns_and_types_are_reported(self, db_file):
        schema = await (await _connected(db_file)).introspect_schema()
        names = {t.name for t in schema.tables}

        assert {"customers", "orders"} <= names
        customers = next(t for t in schema.tables if t.name == "customers")
        assert [c.name for c in customers.columns] == ["id", "name", "country"]
        assert next(c for c in customers.columns if c.name == "id").is_primary_key
        assert not next(c for c in customers.columns if c.name == "name").is_nullable

    async def test_foreign_keys_are_reported(self, db_file):
        schema = await (await _connected(db_file)).introspect_schema()
        orders = next(t for t in schema.tables if t.name == "orders")

        assert len(orders.foreign_keys) == 1
        fk = orders.foreign_keys[0]
        assert (fk.column, fk.references_table, fk.references_column) == (
            "customer_id",
            "customers",
            "id",
        )

    async def test_indexes_are_reported(self, db_file):
        schema = await (await _connected(db_file)).introspect_schema()
        customers = next(t for t in schema.tables if t.name == "customers")

        idx = next(i for i in customers.indexes if i.name == "idx_customer_name")
        assert idx.columns == ["name"]
        assert idx.is_unique

    async def test_views_are_marked_as_views_and_not_counted(self, db_file):
        schema = await (await _connected(db_file)).introspect_schema()
        view = next(t for t in schema.tables if t.name == "paid_totals")

        assert view.object_kind == "view"
        assert view.row_count is None, "counting a view's rows runs the view"

    async def test_row_counts_are_reported_for_tables(self, db_file):
        schema = await (await _connected(db_file)).introspect_schema()

        assert next(t for t in schema.tables if t.name == "customers").row_count == 2

    async def test_sqlite_internal_tables_are_not_offered_to_the_llm(self, db_file):
        """`sqlite_sequence` and friends exist in every database and answer no question
        a user asked; in the schema context they are tokens spent on noise."""
        with sqlite3.connect(db_file) as db:
            db.execute("CREATE TABLE auto (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            db.execute("INSERT INTO auto DEFAULT VALUES")

        schema = await (await _connected(db_file)).introspect_schema()

        assert not [t for t in schema.tables if t.name.startswith("sqlite_")]


class TestHealth:
    async def test_test_connection_is_true_for_a_readable_file(self, db_file):
        assert await (await _connected(db_file)).test_connection() is True

    async def test_test_connection_is_false_before_connect(self):
        assert await SQLiteConnector().test_connection() is False

    async def test_reconnect_reports_honestly(self, db_file):
        """There is no pool and no socket to rebuild, so claiming a repair would make the
        health monitor report one it never performed."""
        assert await SQLiteConnector().reconnect() is False
        assert await (await _connected(db_file)).reconnect() is True

    async def test_disconnect_releases_the_path(self, db_file):
        conn = await _connected(db_file)
        await conn.disconnect()

        assert (await conn.execute_query("SELECT 1")).error == "Not connected"


class TestItNeverCreatesAFileNamedNone:
    """`f"file:{self._path}"` with an unset path yields `file:None`, and a writable
    connection makes SQLite create a file called `None` in the working directory. Every
    caller guards on `_path`; this asserts the guard that does not depend on them."""

    def test_the_uri_refuses_an_unset_path(self):
        with pytest.raises(RuntimeError, match="connect"):
            SQLiteConnector()._uri()

    async def test_a_writable_connector_with_no_path_creates_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        conn = SQLiteConnector()

        assert (await conn.execute_query("SELECT 1")).error == "Not connected"
        assert await conn.test_connection() is False

        assert not (tmp_path / "None").exists()
        assert list(tmp_path.iterdir()) == []
