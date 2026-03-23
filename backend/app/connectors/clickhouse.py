import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import clickhouse_connect

from app.config import settings
from app.connectors.base import (
    BaseConnector,
    ColumnInfo,
    ConnectionConfig,
    IndexInfo,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.connectors.ssh_tunnel import SSHTunnelManager

logger = logging.getLogger(__name__)

_tunnel_mgr = SSHTunnelManager()


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
                logger.debug("ClickHouse: error closing existing client before reconnect", exc_info=True)
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

        self._client = await asyncio.to_thread(
            clickhouse_connect.get_client,
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
        )

    async def disconnect(self) -> None:
        if self._client:
            try:
                await asyncio.to_thread(self._client.close)
            finally:
                self._client = None

    _QUERY_TIMEOUT_S = settings.query_timeout_seconds

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        if not self._client:
            return QueryResult(error="Not connected")

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._client.query, query, parameters=params),
                timeout=self._QUERY_TIMEOUT_S,
            )
            elapsed = (time.monotonic() - start) * 1000

            columns = list(result.column_names) if result.column_names else []
            all_rows = [list(row) for row in result.result_rows] if result.result_rows else []
            from app.connectors.base import MAX_RESULT_ROWS

            truncated = len(all_rows) > MAX_RESULT_ROWS
            rows = all_rows[:MAX_RESULT_ROWS] if truncated else all_rows
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(all_rows),
                execution_time_ms=elapsed,
                truncated=truncated,
            )
        except TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                error=f"Query timed out after {self._QUERY_TIMEOUT_S}s",
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
            tables: list[TableInfo] = []

            tbl_result = client.query(
                "SELECT name, comment, total_rows FROM system.tables WHERE database = %(db)s",
                parameters={"db": db_name},
            )
            for trow in tbl_result.result_rows:
                tname = trow[0]
                tcomment = trow[1] if len(trow) > 1 else ""
                trow_count = trow[2] if len(trow) > 2 else None

                col_result = client.query(
                    "SELECT name, type, default_kind, default_expression, comment "
                    "FROM system.columns "
                    "WHERE database = %(db)s AND table = %(tbl)s",
                    parameters={"db": db_name, "tbl": tname},
                )
                columns = [
                    ColumnInfo(
                        name=c[0],
                        data_type=c[1],
                        is_nullable="Nullable" in c[1],
                        default=c[3] if len(c) > 3 and c[3] else None,
                        comment=c[4] if len(c) > 4 and c[4] else None,
                    )
                    for c in col_result.result_rows
                ]

                indexes: list[IndexInfo] = []
                try:
                    idx_result = client.query(
                        "SELECT name, expr, type "
                        "FROM system.data_skipping_indices "
                        "WHERE database = %(db)s AND table = %(tbl)s",
                        parameters={"db": db_name, "tbl": tname},
                    )
                    for irow in idx_result.result_rows:
                        indexes.append(
                            IndexInfo(
                                name=irow[0],
                                columns=[irow[1]],
                                is_unique=False,
                            )
                        )
                except Exception:
                    logger.debug("ClickHouse index query failed for %s", tname, exc_info=True)

                tables.append(
                    TableInfo(
                        name=tname,
                        schema=db_name,
                        columns=columns,
                        comment=tcomment if tcomment else None,
                        row_count=trow_count,
                        indexes=indexes,
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
