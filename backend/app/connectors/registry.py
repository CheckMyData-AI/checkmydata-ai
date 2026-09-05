from app.connectors.base import BaseConnector, DataSourceAdapter
from app.connectors.clickhouse import ClickHouseConnector
from app.connectors.mcp_client import MCPClientAdapter
from app.connectors.mongodb import MongoDBConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.postgres import PostgresConnector
from app.connectors.sqlite import SQLiteConnector
from app.connectors.ssh_exec import SSHExecConnector

ADAPTER_REGISTRY: dict[str, type[DataSourceAdapter]] = {
    "postgres": PostgresConnector,
    "postgresql": PostgresConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "mongo": MongoDBConnector,
    "clickhouse": ClickHouseConnector,
    # The demo path has created `db_type="sqlite"` connections since it existed, and
    # this map had no entry for it — so every demo connection raised "Unsupported
    # adapter" on the first question asked of it.
    "sqlite": SQLiteConnector,
    "mcp": MCPClientAdapter,
}

#: Accepted names that mean the same engine. The registry decides what a caller
#: may say; this decides what those sayings mean, so a lookup keyed on the engine
#: does not have to repeat the vocabulary.
#:
#: Row 2.12: `DIALECT_HINTS` was keyed on four names while the registry accepted
#: eight, and its lookup fell through silently — so `sqlite` (which is what the
#: demo creates), `postgresql` and `mongo` all reached the agent with no dialect
#: guidance at all.
_DIALECT_ALIASES = {
    "postgresql": "postgres",
    "mongo": "mongodb",
    "mariadb": "mysql",
}


def canonical_dialect(db_type: str) -> str:
    """The engine a `db_type` names, lower-cased and de-aliased.

    An unregistered name is returned unchanged rather than guessed at: a caller
    that invented one should reach the generic fallback, not somebody else's
    dialect.
    """
    key = (db_type or "").strip().lower()
    return _DIALECT_ALIASES.get(key, key)


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
