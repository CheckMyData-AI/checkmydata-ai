import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import clickhouse_connect

from app.connectors.base import (
    BaseConnector,
    ColumnInfo,
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


class ClickHouseConnector(BaseConnector):
    def __init__(self):
        self._client = None
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

        self._client = await asyncio.to_thread(
            clickhouse_connect.get_client,
            **client_kwargs,
        )

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
        if not self._client:
            return QueryResult(error="Not connected")

        client = self._client
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
            tbl_result = client.query(
                "SELECT name, comment, total_rows FROM system.tables WHERE database = %(db)s",
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
                tables.append(
                    TableInfo(
                        name=tname,
                        schema=db_name,
                        columns=columns_by_table.get(tname, []),
                        comment=tcomment if tcomment else None,
                        row_count=trow_count,
                        indexes=indexes_by_table.get(tname, []),
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
