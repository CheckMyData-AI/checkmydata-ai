import pytest

from app.connectors.base import ColumnInfo, ConnectionConfig, TableInfo
from app.connectors.postgres import _build_check_map, _build_enum_map, _normalize_reltuples
from app.connectors.registry import get_connector


class TestRegistry:
    def test_get_postgres(self):
        conn = get_connector("postgres")
        assert conn.db_type == "postgres"

    def test_get_postgresql_alias(self):
        conn = get_connector("postgresql")
        assert conn.db_type == "postgres"

    def test_get_mysql(self):
        conn = get_connector("mysql")
        assert conn.db_type == "mysql"

    def test_get_mongodb(self):
        conn = get_connector("mongodb")
        assert conn.db_type == "mongodb"

    def test_get_mongo_alias(self):
        conn = get_connector("mongo")
        assert conn.db_type == "mongodb"

    def test_get_clickhouse(self):
        conn = get_connector("clickhouse")
        assert conn.db_type == "clickhouse"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_connector("unknown_db")

    def test_case_insensitive(self):
        conn = get_connector("Postgres")
        assert conn.db_type == "postgres"

    def test_case_insensitive_upper(self):
        conn = get_connector("MYSQL")
        assert conn.db_type == "mysql"


class TestResolveQueryTimeout:
    """B2: per-query timeout resolution — dynamic budget capped at the ceiling."""

    def test_none_uses_static_ceiling(self):
        from app.config import settings
        from app.connectors.base import resolve_query_timeout

        assert resolve_query_timeout(None) == float(settings.query_timeout_seconds)

    def test_zero_or_negative_uses_ceiling(self):
        from app.config import settings
        from app.connectors.base import resolve_query_timeout

        assert resolve_query_timeout(0) == float(settings.query_timeout_seconds)
        assert resolve_query_timeout(-5) == float(settings.query_timeout_seconds)

    def test_positive_below_ceiling_is_honored(self):
        from app.config import settings
        from app.connectors.base import resolve_query_timeout

        small = max(1.0, float(settings.query_timeout_seconds) - 1)
        assert resolve_query_timeout(small) == small

    def test_above_ceiling_is_clamped(self):
        from app.config import settings
        from app.connectors.base import resolve_query_timeout

        big = float(settings.query_timeout_seconds) + 100
        assert resolve_query_timeout(big) == float(settings.query_timeout_seconds)


class TestConnectionConfig:
    def test_defaults(self):
        config = ConnectionConfig(db_type="postgres")
        assert config.db_host == "127.0.0.1"
        assert config.db_port == 5432
        assert config.is_read_only is True
        assert config.ssh_host is None

    def test_custom(self):
        config = ConnectionConfig(
            db_type="mysql",
            db_host="db.example.com",
            db_port=3306,
            db_name="mydb",
            db_user="admin",
            db_password="secret",
            ssh_host="jump.example.com",
            ssh_user="deploy",
        )
        assert config.db_type == "mysql"
        assert config.ssh_host == "jump.example.com"


class TestPostgresEnumAndCheck:
    def test_enum_map_groups_labels_in_order(self):
        rows = [
            {
                "table_schema": "public",
                "table_name": "orders",
                "column_name": "status",
                "label": "new",
                "sortorder": 1,
            },
            {
                "table_schema": "public",
                "table_name": "orders",
                "column_name": "status",
                "label": "paid",
                "sortorder": 2,
            },
        ]
        m = _build_enum_map(rows)
        assert m[("public", "orders", "status")] == ["new", "paid"]

    def test_enum_map_respects_sort_order(self):
        rows = [
            {
                "table_schema": "public",
                "table_name": "t",
                "column_name": "c",
                "label": "z",
                "sortorder": 2,
            },
            {
                "table_schema": "public",
                "table_name": "t",
                "column_name": "c",
                "label": "a",
                "sortorder": 1,
            },
        ]
        m = _build_enum_map(rows)
        assert m[("public", "t", "c")] == ["a", "z"]

    def test_enum_map_empty_rows(self):
        assert _build_enum_map([]) == {}

    def test_check_map_collects_expressions(self):
        rows = [{"table_schema": "public", "table_name": "orders", "expr": "amount > 0"}]
        assert _build_check_map(rows)[("public", "orders")] == ["amount > 0"]

    def test_check_map_multiple_constraints_same_table(self):
        rows = [
            {"table_schema": "public", "table_name": "t", "expr": "a > 0"},
            {"table_schema": "public", "table_name": "t", "expr": "b IS NOT NULL"},
        ]
        m = _build_check_map(rows)
        assert m[("public", "t")] == ["a > 0", "b IS NOT NULL"]

    def test_check_map_empty_rows(self):
        assert _build_check_map([]) == {}

    def test_columninfo_gets_enum_labels_when_matched(self):
        ci = ColumnInfo(name="status", data_type="USER-DEFINED", enum_labels=["new", "paid"])
        assert ci.enum_labels == ["new", "paid"]
        assert ColumnInfo(name="x", data_type="int").enum_labels is None
        assert ColumnInfo(name="x", data_type="int").check_constraints == []


class TestNormalizeReltuples:
    def test_negative_reltuples_is_unknown(self):
        assert _normalize_reltuples(-1) is None

    def test_negative_large_is_unknown(self):
        assert _normalize_reltuples(-999) is None

    def test_none_is_unknown(self):
        assert _normalize_reltuples(None) is None

    def test_zero_stays_zero(self):
        assert _normalize_reltuples(0) == 0

    def test_positive_passes_through(self):
        assert _normalize_reltuples(1234) == 1234


class TestObjectKind:
    """DBIDX-D6: VIEW / MATERIALIZED VIEW introspection — object_kind field."""

    # --- TableInfo field --------------------------------------------------

    def test_tableinfo_object_kind_default_is_table(self):
        assert TableInfo(name="t").object_kind == "table"

    # --- Postgres helpers -------------------------------------------------

    def test_pg_maps_base_table_to_table(self):
        from app.connectors.postgres import _map_pg_object_kind

        assert _map_pg_object_kind("BASE TABLE") == "table"

    def test_pg_maps_view_to_view(self):
        from app.connectors.postgres import _map_pg_object_kind

        assert _map_pg_object_kind("VIEW") == "view"

    def test_pg_matview_kind(self):
        from app.connectors.postgres import _map_pg_object_kind

        assert _map_pg_object_kind("MATERIALIZED VIEW") == "matview"

    # --- ClickHouse helpers -----------------------------------------------

    def test_ch_engine_mergetree_is_table(self):
        from app.connectors.clickhouse import _ch_engine_to_kind

        assert _ch_engine_to_kind("MergeTree") == "table"

    def test_ch_engine_view_is_view(self):
        from app.connectors.clickhouse import _ch_engine_to_kind

        assert _ch_engine_to_kind("View") == "view"

    def test_ch_engine_materialized_view_is_matview(self):
        from app.connectors.clickhouse import _ch_engine_to_kind

        assert _ch_engine_to_kind("MaterializedView") == "matview"

    def test_ch_engine_unknown_is_table(self):
        from app.connectors.clickhouse import _ch_engine_to_kind

        assert _ch_engine_to_kind("ReplacingMergeTree") == "table"

    # --- MySQL helper -----------------------------------------------------

    def test_mysql_view_kind(self):
        from app.connectors.mysql import _map_mysql_object_kind

        assert _map_mysql_object_kind("VIEW") == "view"

    def test_mysql_base_table_kind(self):
        from app.connectors.mysql import _map_mysql_object_kind

        assert _map_mysql_object_kind("BASE TABLE") == "table"

    # --- Postgres introspection (monkeypatched) ---------------------------

    def test_pg_introspect_includes_view(self):
        """A VIEW row in information_schema.tables is included with object_kind='view'."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.connectors.postgres import PostgresConnector

        connector = PostgresConnector()

        # Minimal canned rows: one table, one view
        def make_record(**kwargs):
            r = MagicMock()
            r.__getitem__ = lambda self, key: kwargs[key]
            r.get = lambda key, default=None: kwargs.get(key, default)
            return r

        table_row = make_record(
            table_schema="public",
            table_name="orders",
            table_type="BASE TABLE",
            approx_rows=100,
            table_comment=None,
        )
        view_row = make_record(
            table_schema="public",
            table_name="orders_view",
            table_type="VIEW",
            approx_rows=None,
            table_comment=None,
        )

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [table_row, view_row],  # 1) tables (BASE TABLE + VIEW)
                [],  # 2) matviews
                [],  # 3) columns
                [],  # 4) PKs
                [],  # 5) FKs
                [],  # 6) indexes
                [],  # 7) enums
                [],  # 8) checks
            ]
        )
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        connector._pool = mock_pool

        schema = asyncio.get_event_loop().run_until_complete(connector._introspect_schema_inner())

        by_name = {t.name: t for t in schema.tables}
        assert "orders" in by_name
        assert by_name["orders"].object_kind == "table"
        assert "orders_view" in by_name
        assert by_name["orders_view"].object_kind == "view"

    def test_pg_introspect_includes_matview(self):
        """A pg_matviews row is included with object_kind='matview'."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.connectors.postgres import PostgresConnector

        connector = PostgresConnector()

        def make_record(**kwargs):
            r = MagicMock()
            r.__getitem__ = lambda self, key: kwargs[key]
            r.get = lambda key, default=None: kwargs.get(key, default)
            return r

        matview_row = make_record(
            schemaname="public",
            matviewname="sales_summary",
        )

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [],  # 1) tables (none)
                [matview_row],  # 2) matviews
                [],  # 3) columns
                [],  # 4) PKs
                [],  # 5) FKs
                [],  # 6) indexes
                [],  # 7) enums
                [],  # 8) checks
            ]
        )
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        connector._pool = mock_pool

        schema = asyncio.get_event_loop().run_until_complete(connector._introspect_schema_inner())

        by_name = {t.name: t for t in schema.tables}
        assert "sales_summary" in by_name
        assert by_name["sales_summary"].object_kind == "matview"

    # --- MySQL introspection (monkeypatched) ------------------------------

    def test_mysql_introspect_includes_view(self):
        """A VIEW row in information_schema.tables is included with object_kind='view'."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.connectors.mysql import MySQLConnector

        connector = MySQLConnector()
        connector._config = MagicMock(db_name="testdb")

        table_rows = [
            {
                "table_name": "users",
                "table_type": "BASE TABLE",
                "table_rows": 50,
                "table_comment": "",
            },
            {
                "table_name": "active_users",
                "table_type": "VIEW",
                "table_rows": None,
                "table_comment": "",
            },
        ]
        col_rows: list = []
        fk_rows: list = []
        idx_rows: list = []

        mock_cursor = AsyncMock()
        # fetchall() is called 4 times: tables, columns, FKs, indexes
        mock_cursor.fetchall = AsyncMock(
            side_effect=[
                table_rows,
                col_rows,
                fk_rows,
                idx_rows,
            ]
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn_obj = AsyncMock()
        mock_conn_obj.cursor = MagicMock(return_value=mock_cursor)
        mock_conn_obj.__aenter__ = AsyncMock(return_value=mock_conn_obj)
        mock_conn_obj.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn_obj),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        connector._pool = mock_pool

        schema = asyncio.get_event_loop().run_until_complete(connector._introspect_schema_inner())

        by_name = {t.name: t for t in schema.tables}
        assert "users" in by_name
        assert by_name["users"].object_kind == "table"
        assert "active_users" in by_name
        assert by_name["active_users"].object_kind == "view"
