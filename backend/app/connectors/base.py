from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectionConfig:
    db_type: str
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = ""
    db_user: str | None = None
    db_password: str | None = None
    connection_string: str | None = None

    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    ssh_key_content: str | None = None
    ssh_key_passphrase: str | None = None

    ssh_exec_mode: bool = False
    ssh_command_template: str | None = None
    ssh_pre_commands: list[str] | None = None

    is_read_only: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    connection_id: str | None = None


def connector_key(cfg: ConnectionConfig) -> str:
    """Canonical cache key for a ConnectionConfig.

    Used everywhere that needs to match a runtime config back to a
    stored ``Connection`` row or cache slot.  Keep this single source
    of truth instead of duplicating the logic.
    """
    parts = [cfg.db_type, cfg.db_host, str(cfg.db_port), cfg.db_name, str(cfg.ssh_exec_mode)]
    if cfg.ssh_host:
        parts.extend([cfg.ssh_host, str(cfg.ssh_port), cfg.ssh_user or ""])
    return ":".join(parts)


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    default: str | None = None
    comment: str | None = None


@dataclass
class ForeignKeyInfo:
    column: str
    references_table: str
    references_column: str


@dataclass
class IndexInfo:
    name: str
    columns: list[str]
    is_unique: bool = False


@dataclass
class TableInfo:
    name: str
    schema: str = "public"
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int | None = None
    comment: str | None = None


@dataclass
class SchemaInfo:
    tables: list[TableInfo] = field(default_factory=list)
    db_type: str = ""
    db_name: str = ""

    def fingerprint(self) -> dict[str, str]:
        """Return a table-name -> column-signature map for incremental diff.

        The signature is a hash of column names, types, and FK targets so
        we can detect which tables actually changed between introspections.
        """
        import hashlib

        result: dict[str, str] = {}
        for table in self.tables:
            parts = []
            for col in sorted(table.columns, key=lambda c: c.name):
                parts.append(f"{col.name}:{col.data_type}:{col.is_nullable}")
            for fk in sorted(table.foreign_keys, key=lambda f: f.column):
                parts.append(f"fk:{fk.column}->{fk.references_table}.{fk.references_column}")
            sig = hashlib.md5("|".join(parts).encode()).hexdigest()[:12]
            result[f"{table.schema}.{table.name}" if table.schema else table.name] = sig
        return result

    def diff(self, previous: "SchemaInfo") -> dict:
        """Compare against a *previous* schema and return changes.

        Returns ``{"added": [...], "removed": [...], "changed": [...], "unchanged": [...]}``.
        """
        old_fp = previous.fingerprint()
        new_fp = self.fingerprint()
        added = sorted(set(new_fp) - set(old_fp))
        removed = sorted(set(old_fp) - set(new_fp))
        changed = sorted(
            t for t in (set(new_fp) & set(old_fp)) if new_fp[t] != old_fp[t]
        )
        unchanged = sorted(
            t for t in (set(new_fp) & set(old_fp)) if new_fp[t] == old_fp[t]
        )
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged,
        }


MAX_RESULT_ROWS = 10_000


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None
    truncated: bool = False


# -----------------------------------------------------------------------
# DataSourceAdapter — generic interface for ALL data sources
# -----------------------------------------------------------------------


class DataSourceAdapter(ABC):
    """Universal interface for all data sources (databases, APIs, etc.)."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source type identifier (e.g. 'database', 'analytics')."""

    @abstractmethod
    async def connect(self, config: ConnectionConfig) -> None:
        """Establish a connection to the data source."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the connection is alive."""

    @abstractmethod
    async def list_entities(self) -> list[str]:
        """List available entities (tables, collections, etc.)."""

    @abstractmethod
    async def query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Execute a query against the data source."""


# -----------------------------------------------------------------------
# DatabaseAdapter — database-specific extension of DataSourceAdapter
# -----------------------------------------------------------------------


class DatabaseAdapter(DataSourceAdapter):
    """Adapter for SQL / NoSQL databases.

    Adds ``introspect_schema()`` and ``execute_query()`` on top of the
    generic ``DataSourceAdapter``.
    """

    @property
    def source_type(self) -> str:
        return "database"

    @abstractmethod
    async def execute_query(self, query: str, params: dict | None = None) -> QueryResult:
        """Execute a query and return results."""

    @abstractmethod
    async def introspect_schema(self) -> SchemaInfo:
        """Introspect the database schema."""

    async def list_entities(self) -> list[str]:
        schema = await self.introspect_schema()
        return [t.name for t in schema.tables]

    async def query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        return await self.execute_query(query, params)

    def _quote_identifier(self, name: str) -> str:
        """Quote a SQL identifier based on the DB type."""
        if self.db_type == "mysql":
            return f"`{name.replace('`', '``')}`"
        return f'"{name.replace(chr(34), chr(34) + chr(34))}"'

    async def sample_data(
        self,
        table_name: str,
        limit: int = 3,
    ) -> QueryResult:
        """Fetch a few sample rows from a table for LLM context."""
        quoted = self._quote_identifier(table_name)
        return await self.execute_query(
            f"SELECT * FROM {quoted} LIMIT {limit}",
        )

    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return the database type identifier."""


# Backward compatibility — existing connectors extend BaseConnector
BaseConnector = DatabaseAdapter
