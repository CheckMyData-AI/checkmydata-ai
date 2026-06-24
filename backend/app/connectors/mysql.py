import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import aiomysql

from app.config import settings
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
from app.connectors.ssh_tunnel import shared_tunnel_manager

logger = logging.getLogger(__name__)

# R1-4: all connectors share one process-wide tunnel manager.
_tunnel_mgr = shared_tunnel_manager


class MySQLConnector(BaseConnector):
    def __init__(self):
        self._pool: aiomysql.Pool | None = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "mysql"

    async def connect(self, config: ConnectionConfig) -> None:
        if self._pool:
            try:
                self._pool.close()
                await self._pool.wait_closed()
            except Exception:
                logger.debug("MySQL: error closing existing pool before reconnect", exc_info=True)
            self._pool = None
        self._config = config

        # R1/C2: DB-enforced read-only backstop. ``init_command`` runs on every
        # new pooled connection; ``SET SESSION TRANSACTION READ ONLY`` makes the
        # session's default access mode read-only. Because ``autocommit=True``
        # each statement is its own transaction, any write/DDL then raises
        # ``ER_TRANSACTION_READ_ONLY`` at the database, not just the app-layer
        # regex. ``None`` for writable connections leaves behaviour unchanged.
        init_command = "SET SESSION TRANSACTION READ ONLY" if config.is_read_only else None

        if config.connection_string:
            parsed = urlparse(config.connection_string)
            self._pool = await aiomysql.create_pool(
                host=parsed.hostname or "127.0.0.1",
                port=parsed.port or 3306,
                db=parsed.path.lstrip("/") or config.db_name,
                user=parsed.username or "root",
                password=parsed.password or "",
                minsize=1,
                maxsize=5,
                autocommit=True,
                connect_timeout=30,
                init_command=init_command,
            )
        else:
            host, port = await _tunnel_mgr.get_or_create(config)
            self._pool = await aiomysql.create_pool(
                host=host,
                port=port,
                db=config.db_name,
                user=config.db_user or "root",
                password=config.db_password or "",
                minsize=1,
                maxsize=5,
                autocommit=True,
                connect_timeout=30,
                init_command=init_command,
            )

    async def disconnect(self) -> None:
        if self._pool:
            try:
                self._pool.close()
                await self._pool.wait_closed()
            finally:
                self._pool = None

    @staticmethod
    def _dict_to_positional(query: str, params: dict[str, Any]) -> tuple[str, tuple]:
        """Convert :name style params to %s positional params for aiomysql."""
        import re

        ordered: list[Any] = []

        def _replacer(m: re.Match) -> str:
            name = m.group(1)
            if name not in params:
                return m.group(0)
            ordered.append(params[name])
            return "%s"

        converted = re.sub(r":(\w+)", _replacer, query)
        return converted, tuple(ordered)

    _QUERY_TIMEOUT_S = settings.query_timeout_seconds

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        if not self._pool:
            return QueryResult(error="Not connected")
        pool = self._pool

        start = time.monotonic()
        from app.connectors.base import MAX_RESULT_ROWS, cap_rows_by_bytes

        try:
            exec_params: Any = params
            exec_query = query
            if isinstance(params, dict):
                exec_query, exec_params = self._dict_to_positional(query, params)

            async def _run() -> list[dict[str, Any]]:
                async with pool.acquire() as conn:
                    # R2/F-ARCH-5: stream via a server-side (unbuffered) cursor and
                    # pull at most ``MAX_RESULT_ROWS + 1`` rows. ``fetchall()`` on a
                    # buffered cursor materialises the entire (potentially
                    # millions-of-rows) result set in client memory before we cap it
                    # — the OOM bug. ``SSDictCursor`` keeps rows on the server; the
                    # ``+1`` sentinel detects truncation. Closing the cursor drains
                    # any unread rows over the wire one block at a time (bounded
                    # memory) so the pooled connection stays in sync.
                    async with conn.cursor(aiomysql.SSDictCursor) as cur:
                        await cur.execute(exec_query, exec_params)
                        return await cur.fetchmany(MAX_RESULT_ROWS + 1)

            rows = await asyncio.wait_for(_run(), timeout=self._QUERY_TIMEOUT_S)
            elapsed = (time.monotonic() - start) * 1000

            if not rows:
                return QueryResult(row_count=0, execution_time_ms=elapsed)

            columns = list(rows[0].keys())
            truncated = len(rows) > MAX_RESULT_ROWS
            capped = rows[:MAX_RESULT_ROWS] if truncated else rows
            data = [list(r.values()) for r in capped]

            # Byte-level backstop: a bounded row count can still be a huge payload
            # (wide rows / BLOBs). Trim further if the estimate exceeds the cap.
            data, byte_truncated = cap_rows_by_bytes(data)
            truncated = truncated or byte_truncated

            return QueryResult(
                columns=columns,
                rows=data,
                row_count=len(data),
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

    async def _reconnect(self) -> None:
        """Close the stale pool and reconnect (picks up a new tunnel port)."""
        logger.info("MySQL: reconnecting after connection loss")
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
        if self._config:
            await self.connect(self._config)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._pool:
            return SchemaInfo(db_type=self.db_type)

        for attempt in range(2):
            try:
                return await self._introspect_schema_inner()
            except aiomysql.OperationalError as exc:
                if attempt == 0 and self._config:
                    logger.warning(
                        "MySQL introspect_schema lost connection (attempt %d): %s — reconnecting",
                        attempt + 1,
                        exc,
                    )
                    await self._reconnect()
                else:
                    raise
        return SchemaInfo(db_type=self.db_type)

    async def _introspect_schema_inner(self) -> SchemaInfo:
        if not self._pool:
            return SchemaInfo(db_type=self.db_type)

        tables: list[TableInfo] = []
        db_name = self._config.db_name if self._config else ""

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 1) All tables
                await cur.execute(
                    """
                    SELECT table_name, table_rows, table_comment
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    """,
                    (db_name,),
                )
                table_rows = await cur.fetchall()

                # 2) All columns in one bulk query
                await cur.execute(
                    """
                    SELECT table_name, column_name, column_type, is_nullable,
                           column_default, column_key, column_comment
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                    """,
                    (db_name,),
                )
                all_col_rows = await cur.fetchall()
                col_map: dict[str, list[dict]] = {}
                for c in all_col_rows:
                    tname = c.get("TABLE_NAME", c.get("table_name", ""))
                    col_map.setdefault(tname, []).append(c)

                # 3) All FKs in one bulk query
                await cur.execute(
                    """
                    SELECT table_name, column_name,
                           referenced_table_name, referenced_column_name
                    FROM information_schema.key_column_usage
                    WHERE table_schema = %s
                      AND referenced_table_name IS NOT NULL
                    """,
                    (db_name,),
                )
                all_fk_rows = await cur.fetchall()
                fk_map: dict[str, list[ForeignKeyInfo]] = {}
                for fk in all_fk_rows:
                    tname = fk.get("TABLE_NAME", fk.get("table_name", ""))
                    fk_map.setdefault(tname, []).append(
                        ForeignKeyInfo(
                            column=fk.get("COLUMN_NAME", fk.get("column_name", "")),
                            references_table=fk.get(
                                "REFERENCED_TABLE_NAME", fk.get("referenced_table_name", "")
                            ),
                            references_column=fk.get(
                                "REFERENCED_COLUMN_NAME", fk.get("referenced_column_name", "")
                            ),
                        )
                    )

                # 4) All indexes in one bulk query
                await cur.execute(
                    """
                    SELECT table_name, index_name, column_name, non_unique
                    FROM information_schema.statistics
                    WHERE table_schema = %s
                    ORDER BY table_name, index_name, seq_in_index
                    """,
                    (db_name,),
                )
                all_idx_rows = await cur.fetchall()
                # Group by (table_name, index_name)
                raw_idx_map: dict[str, dict[str, tuple[list[str], bool]]] = {}
                for ir in all_idx_rows:
                    tname = ir.get("TABLE_NAME", ir.get("table_name", ""))
                    idx_name = ir.get("INDEX_NAME", ir.get("index_name", ""))
                    col_name = ir.get("COLUMN_NAME", ir.get("column_name", ""))
                    non_unique = ir.get("NON_UNIQUE", ir.get("non_unique", 1))
                    tbl_idxs = raw_idx_map.setdefault(tname, {})
                    if idx_name not in tbl_idxs:
                        tbl_idxs[idx_name] = ([], non_unique == 0)
                    tbl_idxs[idx_name][0].append(col_name)

                # Assemble TableInfo objects
                for tr in table_rows:
                    tname = tr.get("TABLE_NAME", tr.get("table_name", ""))
                    approx_rows = tr.get("TABLE_ROWS", tr.get("table_rows"))
                    table_comment = tr.get("TABLE_COMMENT", tr.get("table_comment")) or None

                    columns = [
                        ColumnInfo(
                            name=c.get("COLUMN_NAME", c.get("column_name", "")),
                            data_type=c.get(
                                "COLUMN_TYPE", c.get("column_type", c.get("DATA_TYPE", ""))
                            ),
                            is_nullable=c.get("IS_NULLABLE", c.get("is_nullable", "YES")) == "YES",
                            is_primary_key=c.get("COLUMN_KEY", c.get("column_key", "")) == "PRI",
                            default=c.get("COLUMN_DEFAULT", c.get("column_default")),
                            comment=c.get("COLUMN_COMMENT", c.get("column_comment")) or None,
                        )
                        for c in col_map.get(tname, [])
                    ]

                    tbl_idx_map = raw_idx_map.get(tname, {})
                    indexes = [
                        IndexInfo(name=name, columns=cols, is_unique=unique)
                        for name, (cols, unique) in tbl_idx_map.items()
                        if name != "PRIMARY"
                    ]

                    tables.append(
                        TableInfo(
                            name=tname,
                            schema=db_name,
                            columns=columns,
                            foreign_keys=fk_map.get(tname, []),
                            indexes=indexes,
                            row_count=int(approx_rows) if approx_rows is not None else None,
                            comment=table_comment,
                        )
                    )

        return SchemaInfo(tables=tables, db_type=self.db_type, db_name=db_name)

    async def test_connection(self) -> bool:
        if not self._pool:
            logger.warning("MySQL test_connection: no pool available")
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("MySQL test_connection failed: %s", exc)
            return False
