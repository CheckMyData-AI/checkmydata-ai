import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


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
    send_sample_data_to_llm: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    connection_id: str | None = None


def connector_key(cfg: ConnectionConfig) -> str:
    """Canonical cache key for a ConnectionConfig.

    Used everywhere that needs to match a runtime config back to a
    stored ``Connection`` row or cache slot.  Keep this single source
    of truth instead of duplicating the logic.

    R1-1: the key includes a credential discriminator so two configs that
    share host/port/db but differ in credentials never collide in the
    process-wide connector pool (which previously caused one connection to
    silently run under another's credentials). We prefer ``connection_id``
    (unique per stored row); for ad-hoc configs without one we fall back to
    a short hash of the credential material. The raw secret is never stored
    in the key.
    """
    parts = [cfg.db_type, cfg.db_host, str(cfg.db_port), cfg.db_name, str(cfg.ssh_exec_mode)]
    if cfg.ssh_host:
        parts.extend([cfg.ssh_host, str(cfg.ssh_port), cfg.ssh_user or ""])

    if cfg.connection_id:
        parts.append(f"cid={cfg.connection_id}")
    else:
        cred_material = "|".join(
            [
                cfg.db_user or "",
                cfg.db_password or "",
                cfg.connection_string or "",
                cfg.ssh_user or "",
                cfg.ssh_key_content or "",
                cfg.ssh_key_passphrase or "",
            ]
        )
        digest = hashlib.sha256(cred_material.encode("utf-8")).hexdigest()[:16]
        parts.append(f"cred={digest}")

    return ":".join(parts)


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    default: str | None = None
    comment: str | None = None
    # C-D schema-capture surface (populated in Wave 4; back-compat defaults):
    enum_labels: list[str] | None = None
    check_constraints: list[str] = field(default_factory=list)
    is_sort_key: bool = False
    distinct_values: list[str] | None = None
    distinct_count: int | None = None
    null_rate: float | None = None
    numeric_format: str | None = None


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
    object_kind: Literal["table", "view", "matview"] = "table"


@dataclass
class SchemaInfo:
    tables: list[TableInfo] = field(default_factory=list)
    db_type: str = ""
    db_name: str = ""
    object_kind: Literal["table", "view", "matview"] = "table"

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
        changed = sorted(t for t in (set(new_fp) & set(old_fp)) if new_fp[t] != old_fp[t])
        unchanged = sorted(t for t in (set(new_fp) & set(old_fp)) if new_fp[t] == old_fp[t])
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged,
        }


MAX_RESULT_ROWS = 10_000


def resolve_query_timeout(timeout_seconds: float | None) -> float:
    """Resolve the effective per-query timeout in seconds.

    A positive caller-supplied ``timeout_seconds`` (a dynamic per-query budget,
    e.g. the pipeline's remaining wall-clock) is honored but never exceeds the
    configured ``query_timeout_seconds`` ceiling — a per-query budget should
    only ever be *shorter* than the global maximum. ``None`` / non-positive
    values fall back to the static ceiling. Imported lazily to keep this
    low-level module free of an import-time dependency on ``app.config``.
    """
    from app.config import settings

    ceiling = float(settings.query_timeout_seconds)
    if timeout_seconds is not None and timeout_seconds > 0:
        return min(float(timeout_seconds), ceiling)
    return ceiling


# Hard cap on the estimated serialized size of a single result payload. The row
# cap (``MAX_RESULT_ROWS``) bounds row *count*, but a bounded number of very wide
# rows (large TEXT/BLOB/JSON columns) can still blow the heap. This is the
# byte-level backstop applied after the row cap.
MAX_RESULT_BYTES = 50_000_000  # 50 MB


def _estimate_value_bytes(value: Any) -> int:
    """Cheap, deterministic byte-size estimate for a single cell value."""
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", "ignore"))
    return len(str(value).encode("utf-8", "ignore"))


def cap_rows_by_bytes(
    rows: list[list[Any]], max_bytes: int = MAX_RESULT_BYTES
) -> tuple[list[list[Any]], bool]:
    """Trim ``rows`` so their estimated serialized size stays under ``max_bytes``.

    Returns ``(possibly_trimmed_rows, truncated)``. ``truncated`` is ``True`` when
    at least one row was dropped to honor the byte budget. The first row is always
    kept so a single oversized row still returns something rather than an empty set.
    """
    total = 0
    for index, row in enumerate(rows):
        total += sum(_estimate_value_bytes(v) for v in row)
        if total > max_bytes and index > 0:
            return rows[:index], True
    return rows, False


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None
    truncated: bool = False


@dataclass
class ColumnStats:
    """Per-column statistics captured during schema introspection (contract C-D).

    Fields are all optional so an adapter can populate what it knows
    without breaking callers that only read a subset.
    """

    distinct_count: int | None = None
    null_rate: float | None = None
    min_value: Any = None
    max_value: Any = None


def derive_result(
    base: QueryResult,
    rows: list[Any],
    *,
    extra_truncation: bool = False,
    columns: list[str] | None = None,
    **overrides: Any,
) -> QueryResult:
    """Carry-forward constructor for a derived ``QueryResult`` (contract C-A).

    Every in-memory transform (aggregate / filter / cohort / enrichment) MUST
    build its result via this helper so ``truncated`` can never be silently
    dropped: ``truncated = base.truncated or extra_truncation``. ``columns``
    defaults to ``base.columns``; ``row_count`` defaults to ``len(rows)``;
    ``execution_time_ms``/``error`` carry from ``base`` unless overridden.
    Passing ``truncated=`` is rejected — the OR is authoritative.
    """
    if "truncated" in overrides:
        raise TypeError(
            "derive_result: pass extra_truncation=..., not truncated= "
            "(truncated is always base.truncated OR extra_truncation)"
        )
    resolved_columns = columns if columns is not None else list(base.columns)
    row_list = list(rows)
    kwargs: dict[str, Any] = {
        "columns": resolved_columns,
        "rows": row_list,
        "row_count": len(row_list),
        "execution_time_ms": base.execution_time_ms,
        "error": base.error,
    }
    kwargs.update(overrides)
    kwargs["truncated"] = base.truncated or extra_truncation
    return QueryResult(**kwargs)


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
    async def execute_query(
        self,
        query: str,
        params: dict | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute a query and return results.

        ``timeout_seconds`` is an optional dynamic per-query budget (e.g. the
        pipeline's remaining wall-clock). When omitted, the configured static
        ``query_timeout_seconds`` ceiling applies. See :func:`resolve_query_timeout`.
        """

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

    async def distinct_values(self, table: str, column: str, limit: int = 50) -> list[str]:
        """Distinct values of a column (dialect-aware; Wave 4 impl). Contract C-D."""
        raise NotImplementedError

    async def approx_stats(self, table: str, column: str) -> ColumnStats:
        """Approximate distinct_count/null_rate/min/max (dialect-aware; Wave 4). Contract C-D."""
        raise NotImplementedError

    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return the database type identifier."""


# Backward compatibility — existing connectors extend BaseConnector
BaseConnector = DatabaseAdapter
