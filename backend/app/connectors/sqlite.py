"""SQLite connector — the one the demo has always claimed to use.

`app/api/routes/demo.py` has created connections with `db_type="sqlite"` since the demo
path existed, and `ADAPTER_REGISTRY` has never had an entry for it:

    >>> get_adapter("database", "sqlite")
    ValueError: Unsupported adapter: sqlite. Available: ['postgres', 'postgresql',
    'mysql', 'mongodb', 'mongo', 'clickhouse', 'mcp']

So the demo produced a connection the product could not open, and the first question a
new user asked it failed. Seeding sample data behind that connection (F-EXP-01) closes
nothing on its own — a database nobody can connect to is the same empty screen with more
work behind it.

Scope: file-backed SQLite, local to the process. No host, no port, no SSH — a SQLite
"connection" is a path, which is also why the demo can hand out one file per user.

**The path must live inside the demo directory, and that is a security boundary, not
tidiness.** Every other connector reaches a database over a network with credentials; a
SQLite connection is a filename on the server's own disk, so "which database" and "which
file may this process read" become the same question. `ConnectionUpdate.db_name` and
`db_type` are free strings, so without this check a user who clicks the demo could
`PATCH` their connection to `./data/agent.db` — the application's own database, holding
every tenant's rows and encrypted credentials — and then ask a question about it. Before
this connector existed the attempt died at `Unsupported adapter: sqlite`; registering it
is what makes the containment load-bearing. The route refuses the same thing one layer
up; neither layer is trusted alone.

**Read-only is enforced by the driver, not by a regex.** `mode=ro` in the URI makes
SQLite itself refuse writes with `SQLITE_READONLY`, matching how the other four
connectors push the guarantee down to the engine (`vision.md` §7 #1). `SafetyGuard`'s
statement allow-list still runs above this, as it does for every raw-SQL entry point;
neither layer is the whole answer.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

from app.connectors.base import (
    BaseConnector,
    ColumnInfo,
    ConnectionConfig,
    ForeignKeyInfo,
    IndexInfo,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.core.error_types import QueryErrorType
from app.core.redaction import safe_error

logger = logging.getLogger(__name__)

#: SQLite's own bookkeeping tables. Present in every database, meaningless to a user
#: asking a question about their data, and noise in the LLM's schema context.
_INTERNAL_PREFIX = "sqlite_"


class SQLiteConnector(BaseConnector):
    """A single file, opened per query.

    There is no pool: SQLite has no server to pool against, and a long-lived handle
    across an async web process is a lock waiting to happen. `connect()` therefore
    validates that the file is reachable and remembers the config; each query opens and
    closes its own connection, which is what makes concurrent readers safe here.
    """

    def __init__(self):
        self._config: ConnectionConfig | None = None
        self._path: str | None = None

    @property
    def db_type(self) -> str:
        return "sqlite"

    def _uri(self) -> str:
        """The connection URI, carrying the read-only mode when the connection is."""
        if not self._path:
            # Interpolating an unset path yields `file:None?mode=rwc`, and on a writable
            # connection SQLite obligingly creates a file literally named `None` in the
            # process's working directory. Every caller guards on `self._path` already;
            # this is the guard that does not depend on all of them continuing to.
            raise RuntimeError("SQLiteConnector has no database path (connect() first)")
        mode = "ro" if (self._config is None or self._config.is_read_only) else "rwc"
        # `mode=ro` also refuses to CREATE the file, which is the behaviour we want:
        # a missing database must surface as an error rather than as an empty one.
        # sqlite3 silently creates the file on a plain path, so a typo'd path would
        # otherwise look exactly like a working connection with no tables in it.
        return f"file:{self._path}?mode={mode}"

    async def connect(self, config: ConnectionConfig) -> None:
        path = (config.db_name or "").strip()
        if not path:
            raise ValueError("SQLite connection has no database file path (db_name is empty)")
        if path == ":memory:":
            # Every fresh connection to `:memory:` is a different, empty database, so a
            # connection configured this way can never see anything written through
            # another one. It reads as "configured" and behaves as "empty" — the exact
            # shape of F-EXP-01 — so it is refused rather than served.
            raise ValueError(
                "SQLite ':memory:' is not a usable connection target: each connection "
                "opens its own empty database. Point db_name at a file."
            )
        resolved = self._within_managed_dir(path)

        self._config = config
        self._path = str(resolved)

        if config.is_read_only and not resolved.exists():
            raise FileNotFoundError(f"SQLite database file not found: {path}")

    @staticmethod
    def _within_managed_dir(path: str) -> Path:
        """Resolve *path* and require it to sit inside the demo directory.

        Resolved first: `demo/../data/agent.db` is inside the directory as a string and
        outside it as a file, and a check on the raw text would pass it. Symlinks resolve
        too, for the same reason.
        """
        from app.services.demo_data import demo_db_dir

        managed = demo_db_dir().resolve()
        try:
            resolved = Path(path).resolve()
        except OSError as exc:
            raise ValueError(f"SQLite path cannot be resolved: {path}") from exc
        if managed not in resolved.parents:
            raise ValueError(
                "SQLite connections are limited to the demo sample database. "
                f"{path!r} is outside {managed}."
            )
        return resolved

    async def disconnect(self) -> None:
        self._config = None
        self._path = None

    async def reconnect(self) -> bool:
        """Nothing to rebuild — there is no pool and no socket. Reported honestly.

        A file either exists at query time or it does not, and re-running `connect()`
        cannot change that, so claiming a successful recovery here would make the health
        monitor report a repair it did not perform.
        """
        return self._path is not None

    async def test_connection(self) -> bool:
        if not self._path:
            return False
        try:
            async with aiosqlite.connect(self._uri(), uri=True) as db:
                await db.execute("SELECT 1")
            return True
        except Exception:
            logger.warning("SQLite: connection test failed", exc_info=True)
            return False

    async def execute_query(
        self,
        query: str,
        params: dict | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        if not self._path:
            return QueryResult(error="Not connected")

        from app.connectors.base import (
            MAX_RESULT_ROWS,
            cap_rows_by_bytes,
            resolve_query_timeout,
        )

        start = time.monotonic()
        timeout_s = resolve_query_timeout(timeout_seconds)

        async def _run() -> tuple[list[str], list[list[Any]]]:
            async with aiosqlite.connect(self._uri(), uri=True) as db:
                cursor = await db.execute(query, params or {})
                try:
                    if cursor.description is None:
                        # A statement that returns no rows (DDL/DML). Only reachable on
                        # a writable connection — the driver refuses these under mode=ro.
                        await db.commit()
                        return [], []
                    columns = [d[0] for d in cursor.description]
                    # +1 sentinel: detects truncation without materialising the rest.
                    fetched = await cursor.fetchmany(MAX_RESULT_ROWS + 1)
                    return columns, [list(r) for r in fetched]
                finally:
                    await cursor.close()

        try:
            columns, rows = await asyncio.wait_for(_run(), timeout=timeout_s)
            elapsed = (time.monotonic() - start) * 1000

            if not columns:
                return QueryResult(row_count=0, execution_time_ms=elapsed)

            truncated = len(rows) > MAX_RESULT_ROWS
            data = rows[:MAX_RESULT_ROWS] if truncated else rows
            data, byte_truncated = cap_rows_by_bytes(data)
            return QueryResult(
                columns=columns,
                rows=data,
                row_count=len(data),
                execution_time_ms=elapsed,
                truncated=truncated or byte_truncated,
            )
        except TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                error=f"Query timed out after {timeout_s:g}s",
                error_type=QueryErrorType.TIMEOUT,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(error=safe_error(e), execution_time_ms=elapsed)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._path:
            return SchemaInfo(db_type=self.db_type)

        info = SchemaInfo(db_type=self.db_type, db_name=Path(self._path).name)
        async with aiosqlite.connect(self._uri(), uri=True) as db:
            objects = await self._fetch(
                db,
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE ? "
                "ORDER BY name",
                (f"{_INTERNAL_PREFIX}%",),
            )
            for name, kind in objects:
                info.tables.append(await self._table_info(db, str(name), str(kind)))
        return info

    async def _table_info(self, db: aiosqlite.Connection, name: str, kind: str) -> TableInfo:
        table = TableInfo(
            name=name,
            schema="main",
            object_kind="view" if kind == "view" else "table",
        )
        quoted = self._quote_identifier(name)

        # PRAGMA takes an identifier, not a bindable parameter, so the name is quoted
        # rather than bound. It comes from sqlite_master — this database's own catalogue
        # — and never from a user string.
        for _cid, col, decl_type, notnull, default, pk in await self._fetch(
            db, f"PRAGMA table_info({quoted})"
        ):
            table.columns.append(
                ColumnInfo(
                    name=str(col),
                    # SQLite columns can be declared with no type at all (it is
                    # dynamically typed). Reporting "" would read as a missing value;
                    # "BLOB" is what SQLite itself assigns such a column's affinity.
                    data_type=str(decl_type) if decl_type else "BLOB",
                    is_nullable=not notnull,
                    is_primary_key=bool(pk),
                    default=str(default) if default is not None else None,
                )
            )

        for row in await self._fetch(db, f"PRAGMA foreign_key_list({quoted})"):
            # (id, seq, table, from, to, on_update, on_delete, match)
            target_table, from_col, to_col = row[2], row[3], row[4]
            table.foreign_keys.append(
                ForeignKeyInfo(
                    column=str(from_col),
                    references_table=str(target_table),
                    # A FK with no explicit target column references the parent's
                    # primary key; SQLite reports NULL there rather than resolving it.
                    references_column=str(to_col) if to_col is not None else "rowid",
                )
            )

        for _seq, idx_name, unique, *_rest in await self._fetch(db, f"PRAGMA index_list({quoted})"):
            cols = [
                str(r[2])
                for r in await self._fetch(
                    db, f"PRAGMA index_info({self._quote_identifier(str(idx_name))})"
                )
                if r[2] is not None
            ]
            table.indexes.append(
                IndexInfo(name=str(idx_name), columns=cols, is_unique=bool(unique))
            )

        if table.object_kind == "table":
            counted = await self._fetch(db, f"SELECT COUNT(*) FROM {quoted}")
            table.row_count = int(counted[0][0]) if counted else None

        return table

    @staticmethod
    async def _fetch(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = await db.execute(sql, params)
        try:
            return [tuple(r) for r in await cursor.fetchall()]
        finally:
            await cursor.close()
