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


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None


class BaseConnector(ABC):
    @abstractmethod
    async def connect(self, config: ConnectionConfig) -> None:
        """Establish connection to the database."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection."""

    @abstractmethod
    async def execute_query(self, query: str, params: dict | None = None) -> QueryResult:
        """Execute a query and return results."""

    @abstractmethod
    async def introspect_schema(self) -> SchemaInfo:
        """Introspect the database schema."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the connection is alive."""

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
