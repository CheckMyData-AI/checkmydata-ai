from app.connectors.base import BaseConnector, DataSourceAdapter
from app.connectors.clickhouse import ClickHouseConnector
from app.connectors.mcp_client import MCPClientAdapter
from app.connectors.mongodb import MongoDBConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.postgres import PostgresConnector
from app.connectors.ssh_exec import SSHExecConnector

ADAPTER_REGISTRY: dict[str, type[DataSourceAdapter]] = {
    "postgres": PostgresConnector,
    "postgresql": PostgresConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "mongo": MongoDBConnector,
    "clickhouse": ClickHouseConnector,
    "mcp": MCPClientAdapter,
}

# Backward compatibility
CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = ADAPTER_REGISTRY  # type: ignore[assignment]


def get_adapter(
    source_type: str,
    db_type: str = "",
    *,
    ssh_exec_mode: bool = False,
) -> DataSourceAdapter:
    """Get an adapter instance for the given source type / db type."""
    if ssh_exec_mode:
        return SSHExecConnector()
    key = db_type.lower() if db_type else source_type.lower()
    cls = ADAPTER_REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"Unsupported adapter: {key}. Available: {list(ADAPTER_REGISTRY.keys())}")
    return cls()


def get_connector(db_type: str, *, ssh_exec_mode: bool = False) -> BaseConnector:
    """Backward-compatible — delegates to ``get_adapter``."""
    adapter = get_adapter("database", db_type, ssh_exec_mode=ssh_exec_mode)
    if not isinstance(adapter, BaseConnector):
        raise TypeError(f"Adapter for '{db_type}' is not a database connector")
    return adapter
