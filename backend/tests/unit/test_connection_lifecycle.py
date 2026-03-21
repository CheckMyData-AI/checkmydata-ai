"""Connection lifecycle tests.

Covers connector registry, connection config building,
encryption round-trips, and SSH tunnel edge cases.
"""

import pytest

from app.connectors.base import ConnectionConfig, DatabaseAdapter, DataSourceAdapter
from app.connectors.registry import ADAPTER_REGISTRY, get_adapter, get_connector
from app.services.encryption import decrypt, encrypt


class TestAdapterRegistry:
    def test_postgres_registered(self):
        assert "postgres" in ADAPTER_REGISTRY
        assert "postgresql" in ADAPTER_REGISTRY

    def test_mysql_registered(self):
        assert "mysql" in ADAPTER_REGISTRY

    def test_mongodb_registered(self):
        assert "mongodb" in ADAPTER_REGISTRY
        assert "mongo" in ADAPTER_REGISTRY

    def test_clickhouse_registered(self):
        assert "clickhouse" in ADAPTER_REGISTRY

    def test_mcp_registered(self):
        assert "mcp" in ADAPTER_REGISTRY

    def test_get_adapter_postgres(self):
        adapter = get_adapter("database", "postgres")
        assert isinstance(adapter, DataSourceAdapter)

    def test_get_adapter_mysql(self):
        adapter = get_adapter("database", "mysql")
        assert isinstance(adapter, DataSourceAdapter)

    def test_get_adapter_mongodb(self):
        adapter = get_adapter("database", "mongodb")
        assert isinstance(adapter, DataSourceAdapter)

    def test_get_adapter_clickhouse(self):
        adapter = get_adapter("database", "clickhouse")
        assert isinstance(adapter, DataSourceAdapter)

    def test_get_adapter_mcp(self):
        adapter = get_adapter("mcp", "mcp")
        assert isinstance(adapter, DataSourceAdapter)

    def test_get_connector_backward_compat(self):
        connector = get_connector("postgres")
        assert isinstance(connector, DatabaseAdapter)

    def test_get_connector_mcp_raises_typeerror(self):
        with pytest.raises(TypeError):
            get_connector("mcp")

    def test_unknown_adapter_raises(self):
        with pytest.raises(ValueError):
            get_adapter("database", "oracle")


class TestEncryptionRoundTrip:
    def test_simple_text(self):
        assert decrypt(encrypt("hello world")) == "hello world"

    def test_special_characters(self):
        val = "p@$$w0rd!#%^&*()_+{}|:<>?"
        assert decrypt(encrypt(val)) == val

    def test_unicode(self):
        val = "パスワード日本語"
        assert decrypt(encrypt(val)) == val

    def test_empty_string(self):
        assert decrypt(encrypt("")) == ""

    def test_long_string(self):
        val = "x" * 10000
        assert decrypt(encrypt(val)) == val

    def test_connection_string_with_special_chars(self):
        val = "postgresql://user:p@ss%23word@host:5432/db?sslmode=require"
        assert decrypt(encrypt(val)) == val

    def test_ssh_private_key(self):
        val = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU=\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )
        assert decrypt(encrypt(val)) == val

    def test_json_env_vars(self):
        val = '{"API_KEY": "sk-abc123", "SECRET": "s3cr3t!"}'
        assert decrypt(encrypt(val)) == val


class TestConnectionConfig:
    def test_basic_config(self):
        config = ConnectionConfig(
            db_type="postgres",
            db_host="localhost",
            db_port=5432,
            db_name="test",
            db_user="user",
            db_password="pass",
        )
        assert config.db_type == "postgres"
        assert config.db_host == "localhost"

    def test_ssh_config(self):
        config = ConnectionConfig(
            db_type="mysql",
            db_host="127.0.0.1",
            db_port=3306,
            db_name="app",
            db_user="root",
            db_password="secret",
            ssh_host="jump.server.com",
            ssh_port=22,
            ssh_user="deploy",
            ssh_key_content="key-content",
        )
        assert config.ssh_host == "jump.server.com"

    def test_ssh_exec_mode(self):
        config = ConnectionConfig(
            db_type="mysql",
            db_host="127.0.0.1",
            ssh_exec_mode=True,
            ssh_command_template="mysql -h {host} -P {port} -u {user} -p{password} {database}",
            ssh_pre_commands=["source /etc/profile"],
        )
        assert config.ssh_exec_mode is True
        assert config.ssh_pre_commands is not None

    def test_mcp_config_extra(self):
        config = ConnectionConfig(
            db_type="mcp",
            extra={
                "mcp_transport_type": "stdio",
                "mcp_server_command": "npx",
                "mcp_server_args": ["-y", "@some/mcp-server"],
            },
        )
        assert config.extra["mcp_transport_type"] == "stdio"

    def test_read_only_default(self):
        config = ConnectionConfig(db_type="postgres")
        assert config.is_read_only is True

    def test_connector_key_deterministic(self):
        from app.connectors.base import connector_key

        c1 = ConnectionConfig(db_type="postgres", db_host="h", db_port=5432, db_name="db")
        c2 = ConnectionConfig(db_type="postgres", db_host="h", db_port=5432, db_name="db")
        assert connector_key(c1) == connector_key(c2)

    def test_connector_key_different(self):
        from app.connectors.base import connector_key

        c1 = ConnectionConfig(db_type="postgres", db_host="h1", db_port=5432, db_name="db")
        c2 = ConnectionConfig(db_type="postgres", db_host="h2", db_port=5432, db_name="db")
        assert connector_key(c1) != connector_key(c2)
