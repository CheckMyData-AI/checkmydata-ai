import pytest

from app.connectors.base import ConnectionConfig
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
