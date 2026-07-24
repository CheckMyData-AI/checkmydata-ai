import asyncio
import logging
import re
import time
from typing import Any, Literal
from urllib.parse import urlparse

import clickhouse_connect

from app.connectors.base import (
    BaseConnector,
    ColumnInfo,
    ColumnStats,
    ConnectionConfig,
    IndexInfo,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.connectors.ssh_tunnel import shared_tunnel_manager

logger = logging.getLogger(__name__)

# R1-4: all connectors share one process-wide tunnel manager.
_tunnel_mgr = shared_tunnel_manager


def _parse_ch_key_columns(sorting_key: str, primary_key: str) -> set[str]:
    """Return the set of bare column names referenced by a ClickHouse sorting/primary key.

    ClickHouse stores the key as a comma-separated expression string, e.g.
    ``"user_id, toDate(ts)"``.  We extract every identifier token from each
    comma-separated fragment via a simple regex so that both bare column names
    and function-argument column names are captured.  The caller intersects this
    set with the table's real column names to avoid false positives from
    function names themselves (e.g. ``toDate`` is not a column).

    Examples::

        _parse_ch_key_columns("user_id, created_at", "")
        # → {"user_id", "created_at"}

        _parse_ch_key_columns("toDate(ts), user_id", "")
        # → {"toDate", "ts", "user_id"}  (caller intersects with real cols → ts, user_id)

        _parse_ch_key_columns("", "")
        # → set()
    """
    candidates: set[str] = set()
    for key_expr in (sorting_key, primary_key):
        key_expr = key_expr.strip()
        if not key_expr:
            continue
        # Split on top-level commas (ClickHouse keys are flat — no nested commas
        # in practice, but regex extraction handles the general case).
        for token in key_expr.split(","):
            for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", token):
                candidates.add(ident)
    return candidates


def _ch_engine_to_kind(engine: str) -> Literal["table", "view", "matview"]:
    """Map a ClickHouse ``system.tables.engine`` value to an ``object_kind`` string.

    - ``"View"``              → ``"view"``
    - ``"MaterializedView"``  → ``"matview"``
    - anything else           → ``"table"``
    """
    if engine == "View":
        return "view"
    if engine == "MaterializedView":
        return "matview"
    return "table"


class ClickHouseConnector(BaseConnector):
    def __init__(self):
        self._client = None
        self._client_kwargs: dict[str, Any] | None = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "clickhouse"

    async def connect(self, config: ConnectionConfig) -> None:
        if self._client:
            try:
                await asyncio.to_thread(self._client.close)
            except Exception:
                logger.debug(
                    "ClickHouse: error closing existing client before reconnect", exc_info=True
                )
            self._client = None
        self._config = config

        if config.connection_string:
            parsed = urlparse(config.connection_string)
            host = parsed.hostname or config.db_host
            port = parsed.port or config.db_port
            database = (parsed.path or "").lstrip("/") or config.db_name
            username = parsed.username or config.db_user or "default"
            password = parsed.password or config.db_password or ""
        else:
            host, port = await _tunnel_mgr.get_or_create(config)
            database = config.db_name
            username = config.db_user or "default"
            password = config.db_password or ""

        client_kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "password": password,
        }
        if config.is_read_only:
            # C3 (R1): DB-enforced read-only session. readonly=1 makes the
            # ClickHouse server reject writes and setting changes — an
            # authoritative backstop behind the app-layer SafetyGuard.
            client_kwargs["settings"] = {"readonly": 1}

        # Kept so a poisoned session (client-side timeout, see execute_query)
        # can be recreated lazily on the next query without a full reconnect.
        self._client_kwargs = client_kwargs
        self._client = await asyncio.to_thread(
            clickhouse_connect.get_client,
            **client_kwargs,
        )

    async def _get_client(self):
        """Return the live client, recreating it if a previous query dropped it.

        After a client-side timeout the driver session is poisoned (the worker
        thread still holds the HTTP stream, so any further query on it fails
        with "concurrent queries within the same session"). The timed-out path
        resets ``self._client`` to None; the next query recreates a fresh
        session here from the stored connect kwargs.
        """
        if self._client is None and self._client_kwargs is not None:
            try:
                self._client = await asyncio.to_thread(
                    clickhouse_connect.get_client,
                    **self._client_kwargs,
                )
            except Exception:
                logger.debug("ClickHouse: lazy client recreation failed", exc_info=True)
        return self._client

    async def _reset_client(self) -> None:
        """Close the current client and drop it so the next query recreates it."""
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                logger.debug("ClickHouse: error closing timed-out client", exc_info=True)

    async def disconnect(self) -> None:
        if self._client:
            try:
                await asyncio.to_thread(self._client.close)
            finally:
                self._client = None

    async def execute_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        client = await self._get_client()
        if client is None:
            return QueryResult(error="Not connected")

        start = time.monotonic()

        from app.connectors.base import MAX_RESULT_ROWS, cap_rows_by_bytes, resolve_query_timeout

        effective_timeout = resolve_query_timeout(timeout_seconds)

        def _run_streaming() -> tuple[list[str], list[list[Any]], bool]:
            """Stream row blocks and stop at the cap (R2-1 class fix).

            The legacy path (``client.query``) materialised the *entire*
            result set in memory before the row cap was applied — the same
            OOM bug PG/MySQL had. ``query_row_block_stream`` pulls blocks
            incrementally; exiting the ``with`` early closes the HTTP
            response so the server stops sending.
            """
            with client.query_row_block_stream(query, parameters=params) as stream:
                columns = list(stream.source.column_names or [])
                rows: list[list[Any]] = []
                truncated = False
                for block in stream:
                    for row in block:
                        if len(rows) >= MAX_RESULT_ROWS:
                            truncated = True
                            break
                        rows.append(list(row))
                    if truncated:
                        break
                return columns, rows, truncated

        try:
            columns, rows, truncated = await asyncio.wait_for(
                asyncio.to_thread(_run_streaming),
                timeout=effective_timeout,
            )
            elapsed = (time.monotonic() - start) * 1000

            # Byte-level backstop alongside the row cap (wide rows / BLOBs).
            rows, byte_truncated = cap_rows_by_bytes(rows)
            truncated = truncated or byte_truncated
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
                truncated=truncated,
            )
        except TimeoutError:
            # B2 (audit): cancelling the coroutine does NOT stop the worker
            # thread — its HTTP stream keeps the driver session busy, so every
            # later query on this client fails with "Attempt to execute
            # concurrent queries within the same session" until the server-side
            # query finishes. Drop the poisoned client; the next query lazily
            # recreates a fresh session via _get_client().
            await self._reset_client()
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                error=f"Query timed out after {effective_timeout:g}s",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(error=str(e), execution_time_ms=elapsed)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._client:
            return SchemaInfo(db_type=self.db_type)

        db_name = self._config.db_name if self._config else "default"
        client = self._client

        def _introspect():
            """Introspect all tables / columns / indexes in three queries (T17).

            Previously this issued 1 + 2 * N queries (one per table for
            columns and one for indexes). We now pull everything at once
            from ``system.columns`` / ``system.data_skipping_indices`` and
            group in Python.
            """
            # Fetch sorting_key, primary_key, and engine alongside the usual table
            # metadata (DBIDX-D4 / DBIDX-D6).  Older ClickHouse versions that lack
            # these columns will return rows with len < 5; we guard with len() checks.
            # ``engine`` distinguishes View / MaterializedView from regular tables.
            tbl_result = client.query(
                "SELECT name, comment, total_rows, sorting_key, primary_key, engine "
                "FROM system.tables WHERE database = %(db)s",
                parameters={"db": db_name},
            )

            col_result = client.query(
                "SELECT table, name, type, default_kind, default_expression, comment "
                "FROM system.columns WHERE database = %(db)s",
                parameters={"db": db_name},
            )
            columns_by_table: dict[str, list[ColumnInfo]] = {}
            for c in col_result.result_rows:
                tbl = c[0]
                columns_by_table.setdefault(tbl, []).append(
                    ColumnInfo(
                        name=c[1],
                        data_type=c[2],
                        is_nullable="Nullable" in c[2],
                        default=c[4] if len(c) > 4 and c[4] else None,
                        comment=c[5] if len(c) > 5 and c[5] else None,
                    )
                )

            indexes_by_table: dict[str, list[IndexInfo]] = {}
            try:
                idx_result = client.query(
                    "SELECT table, name, expr, type "
                    "FROM system.data_skipping_indices "
                    "WHERE database = %(db)s",
                    parameters={"db": db_name},
                )
                for irow in idx_result.result_rows:
                    tbl = irow[0]
                    indexes_by_table.setdefault(tbl, []).append(
                        IndexInfo(
                            name=irow[1],
                            columns=[irow[2]],
                            is_unique=False,
                        )
                    )
            except Exception:
                logger.debug("ClickHouse bulk index query failed", exc_info=True)

            tables: list[TableInfo] = []
            for trow in tbl_result.result_rows:
                tname = trow[0]
                tcomment = trow[1] if len(trow) > 1 else ""
                trow_count = trow[2] if len(trow) > 2 else None
                # sorting_key / primary_key are present on CH ≥ 20.x; guard for
                # older deployments that may return shorter rows (DBIDX-D4 DoD).
                sorting_key = trow[3] if len(trow) > 3 and trow[3] else ""
                primary_key = trow[4] if len(trow) > 4 and trow[4] else ""
                # engine column added in DBIDX-D6; guard for rows from older
                # ClickHouse deployments that may have fewer columns.
                engine = trow[5] if len(trow) > 5 and trow[5] else ""

                # Build the candidate key-column set and intersect with real column
                # names to avoid false positives from function names (e.g. "toDate").
                real_col_names = {c.name for c in columns_by_table.get(tname, [])}
                key_candidates = _parse_ch_key_columns(sorting_key, primary_key)
                key_cols = key_candidates & real_col_names

                # Apply is_sort_key to the ColumnInfo objects in-place.
                final_cols: list[ColumnInfo] = []
                for col in columns_by_table.get(tname, []):
                    if col.name in key_cols:
                        final_cols.append(
                            ColumnInfo(
                                name=col.name,
                                data_type=col.data_type,
                                is_nullable=col.is_nullable,
                                default=col.default,
                                comment=col.comment,
                                is_sort_key=True,
                            )
                        )
                    else:
                        final_cols.append(col)

                tables.append(
                    TableInfo(
                        name=tname,
                        schema=db_name,
                        columns=final_cols,
                        comment=tcomment if tcomment else None,
                        row_count=trow_count,
                        indexes=indexes_by_table.get(tname, []),
                        object_kind=_ch_engine_to_kind(engine),
                    )
                )
            return tables

        tables = await asyncio.to_thread(_introspect)
        return SchemaInfo(tables=tables, db_type=self.db_type, db_name=db_name)

    async def test_connection(self) -> bool:
        if not self._client:
            logger.warning("ClickHouse test_connection: no client available")
            return False
        try:
            await asyncio.to_thread(self._client.query, "SELECT 1")
            return True
        except Exception as exc:
            logger.warning("ClickHouse test_connection failed: %s", exc)
            return False

    async def approx_stats(self, table: str, column: str) -> ColumnStats:
        """ClickHouse override: use ``uniqExact`` / ``countIf`` / ``min`` / ``max``.

        ClickHouse supports backtick-quoted identifiers.  Standard
        ``COUNT(DISTINCT ...)`` is valid SQL but ``uniqExact`` is the idiomatic
        ClickHouse function that matches ``DISTINCT`` semantics exactly.
        ``countIf(col IS NULL)`` replaces the CASE-based null counter from the
        base implementation.  Contract C-D / DBIDX-D9.
        """

        def _bq(name: str) -> str:
            """Backtick-quote a ClickHouse identifier."""
            return f"`{name.replace('`', '``')}`"

        tq = _bq(table)
        cq = _bq(column)
        qr = await self.execute_query(
            f"SELECT uniqExact({cq}) AS dc, "
            f"countIf({cq} IS NULL) AS nulls, "
            f"count() AS total, "
            f"min({cq}) AS mn, "
            f"max({cq}) AS mx "
            f"FROM {tq}"
        )
        if qr.error or not qr.rows:
            return ColumnStats()
        dc, nulls, total, mn, mx = qr.rows[0]
        null_rate = (nulls / total) if total else None
        return ColumnStats(distinct_count=dc, null_rate=null_rate, min_value=mn, max_value=mx)
