import time
from typing import Any
from urllib.parse import urlparse

import aiomysql

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
from app.connectors.ssh_tunnel import SSHTunnelManager

_tunnel_mgr = SSHTunnelManager()


class MySQLConnector(BaseConnector):
    def __init__(self):
        self._pool: aiomysql.Pool | None = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "mysql"

    async def connect(self, config: ConnectionConfig) -> None:
        self._config = config

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
            )

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        if not self._pool:
            return QueryResult(error="Not connected")

        start = time.monotonic()
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
                    elapsed = (time.monotonic() - start) * 1000

                    if not rows:
                        return QueryResult(row_count=0, execution_time_ms=elapsed)

                    columns = list(rows[0].keys())
                    data = [list(r.values()) for r in rows]
                    return QueryResult(
                        columns=columns,
                        rows=data,
                        row_count=len(data),
                        execution_time_ms=elapsed,
                    )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(error=str(e), execution_time_ms=elapsed)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._pool:
            return SchemaInfo(db_type=self.db_type)

        tables: list[TableInfo] = []
        db_name = self._config.db_name if self._config else ""

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT table_name, table_rows, table_comment
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    """,
                    (db_name,),
                )
                table_rows = await cur.fetchall()

                for tr in table_rows:
                    tname = tr.get("TABLE_NAME", tr.get("table_name", ""))
                    approx_rows = tr.get("TABLE_ROWS", tr.get("table_rows"))
                    table_comment = tr.get("TABLE_COMMENT", tr.get("table_comment")) or None

                    await cur.execute(
                        """
                        SELECT column_name, column_type, is_nullable,
                               column_default, column_key, column_comment
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (db_name, tname),
                    )
                    col_rows = await cur.fetchall()
                    columns = [
                        ColumnInfo(
                            name=c.get("COLUMN_NAME", c.get("column_name", "")),
                            data_type=c.get("COLUMN_TYPE", c.get("column_type", c.get("DATA_TYPE", ""))),
                            is_nullable=c.get("IS_NULLABLE", c.get("is_nullable", "YES")) == "YES",
                            is_primary_key=c.get("COLUMN_KEY", c.get("column_key", "")) == "PRI",
                            default=c.get("COLUMN_DEFAULT", c.get("column_default")),
                            comment=c.get("COLUMN_COMMENT", c.get("column_comment")) or None,
                        )
                        for c in col_rows
                    ]

                    await cur.execute(
                        """
                        SELECT column_name, referenced_table_name, referenced_column_name
                        FROM information_schema.key_column_usage
                        WHERE table_schema = %s AND table_name = %s
                          AND referenced_table_name IS NOT NULL
                        """,
                        (db_name, tname),
                    )
                    fk_rows = await cur.fetchall()
                    foreign_keys = [
                        ForeignKeyInfo(
                            column=fk.get("COLUMN_NAME", fk.get("column_name", "")),
                            references_table=fk.get("REFERENCED_TABLE_NAME", fk.get("referenced_table_name", "")),
                            references_column=fk.get("REFERENCED_COLUMN_NAME", fk.get("referenced_column_name", "")),
                        )
                        for fk in fk_rows
                    ]

                    await cur.execute(
                        """
                        SELECT index_name, column_name, non_unique
                        FROM information_schema.statistics
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY index_name, seq_in_index
                        """,
                        (db_name, tname),
                    )
                    idx_rows = await cur.fetchall()
                    idx_map: dict[str, tuple[list[str], bool]] = {}
                    for ir in idx_rows:
                        idx_name = ir.get("INDEX_NAME", ir.get("index_name", ""))
                        col_name = ir.get("COLUMN_NAME", ir.get("column_name", ""))
                        non_unique = ir.get("NON_UNIQUE", ir.get("non_unique", 1))
                        if idx_name not in idx_map:
                            idx_map[idx_name] = ([], non_unique == 0)
                        idx_map[idx_name][0].append(col_name)
                    indexes = [
                        IndexInfo(name=name, columns=cols, is_unique=unique)
                        for name, (cols, unique) in idx_map.items()
                    ]

                    tables.append(TableInfo(
                        name=tname,
                        columns=columns,
                        foreign_keys=foreign_keys,
                        indexes=indexes,
                        row_count=int(approx_rows) if approx_rows is not None else None,
                        comment=table_comment,
                    ))

        return SchemaInfo(tables=tables, db_type=self.db_type, db_name=db_name)

    async def test_connection(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
            return True
        except Exception:
            return False
