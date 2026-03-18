import logging
import re
import time
from typing import Any

import asyncpg

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

logger = logging.getLogger(__name__)

_tunnel_mgr = SSHTunnelManager()


class PostgresConnector(BaseConnector):
    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "postgres"

    async def connect(self, config: ConnectionConfig) -> None:
        self._config = config

        if config.connection_string:
            self._pool = await asyncpg.create_pool(config.connection_string, min_size=1, max_size=5)
        else:
            host, port = await _tunnel_mgr.get_or_create(config)
            self._pool = await asyncpg.create_pool(
                host=host,
                port=port,
                database=config.db_name,
                user=config.db_user,
                password=config.db_password,
                min_size=1,
                max_size=5,
            )

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        if not self._pool:
            return QueryResult(error="Not connected")

        start = time.monotonic()
        try:
            async with self._pool.acquire() as conn:
                if params:
                    numbered_query, values = _dict_to_positional(query, params)
                    rows = await conn.fetch(numbered_query, *values)
                else:
                    rows = await conn.fetch(query)

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

    async def _reconnect(self) -> None:
        """Close the stale pool and reconnect (picks up a new tunnel port)."""
        logger.info("Postgres: reconnecting after connection loss")
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._config:
            await self.connect(self._config)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._pool:
            return SchemaInfo(db_type=self.db_type)

        for attempt in range(2):
            try:
                return await self._introspect_schema_inner()
            except (asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError, OSError) as exc:
                if attempt == 0 and self._config:
                    logger.warning(
                        "Postgres introspect_schema lost connection "
                        "(attempt %d): %s — reconnecting",
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
        async with self._pool.acquire() as conn:
            table_rows = await conn.fetch(
                """
                SELECT t.table_schema, t.table_name,
                       c.reltuples::bigint AS approx_rows,
                       obj_description(c.oid) AS table_comment
                FROM information_schema.tables t
                JOIN pg_class c ON c.relname = t.table_name
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
                WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_schema, t.table_name
                """
            )
            for tr in table_rows:
                schema_name = tr["table_schema"]
                table_name = tr["table_name"]

                col_rows = await conn.fetch(
                    """
                    SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                           pgd.description AS column_comment
                    FROM information_schema.columns c
                    LEFT JOIN pg_catalog.pg_statio_all_tables st
                        ON st.schemaname = c.table_schema AND st.relname = c.table_name
                    LEFT JOIN pg_catalog.pg_description pgd
                        ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
                    WHERE c.table_schema = $1 AND c.table_name = $2
                    ORDER BY c.ordinal_position
                    """,
                    schema_name,
                    table_name,
                )
                pk_rows = await conn.fetch(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    JOIN pg_class c ON c.oid = i.indrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE i.indisprimary AND n.nspname = $1 AND c.relname = $2
                    """,
                    schema_name,
                    table_name,
                )
                pk_names = {r["attname"] for r in pk_rows}

                columns = [
                    ColumnInfo(
                        name=c["column_name"],
                        data_type=c["data_type"],
                        is_nullable=c["is_nullable"] == "YES",
                        is_primary_key=c["column_name"] in pk_names,
                        default=c["column_default"],
                        comment=c["column_comment"],
                    )
                    for c in col_rows
                ]

                fk_rows = await conn.fetch(
                    """
                    SELECT
                        a_child.attname AS column_name,
                        cl_parent.relname AS references_table,
                        a_parent.attname AS references_column
                    FROM pg_constraint con
                    JOIN pg_class cl_child ON cl_child.oid = con.conrelid
                    JOIN pg_namespace ns ON ns.oid = cl_child.relnamespace
                    JOIN pg_class cl_parent ON cl_parent.oid = con.confrelid
                    CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
                        WITH ORDINALITY AS u(child_attnum, parent_attnum, ord)
                    JOIN pg_attribute a_child ON a_child.attrelid = con.conrelid
                        AND a_child.attnum = u.child_attnum
                    JOIN pg_attribute a_parent ON a_parent.attrelid = con.confrelid
                        AND a_parent.attnum = u.parent_attnum
                    WHERE con.contype = 'f' AND ns.nspname = $1 AND cl_child.relname = $2
                    """,
                    schema_name,
                    table_name,
                )
                foreign_keys = [
                    ForeignKeyInfo(
                        column=fk["column_name"],
                        references_table=fk["references_table"],
                        references_column=fk["references_column"],
                    )
                    for fk in fk_rows
                ]

                idx_rows = await conn.fetch(
                    """
                    SELECT ic.relname AS index_name, i.indisunique,
                           array_agg(a.attname ORDER BY k.n) AS columns
                    FROM pg_index i
                    JOIN pg_class ic ON ic.oid = i.indexrelid
                    JOIN pg_class tc ON tc.oid = i.indrelid
                    JOIN pg_namespace ns ON ns.oid = tc.relnamespace
                    CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, n)
                    JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = k.attnum
                    WHERE NOT i.indisprimary AND ns.nspname = $1 AND tc.relname = $2
                    GROUP BY ic.relname, i.indisunique
                    """,
                    schema_name,
                    table_name,
                )
                indexes = [
                    IndexInfo(
                        name=ir["index_name"],
                        columns=list(ir["columns"]),
                        is_unique=ir["indisunique"],
                    )
                    for ir in idx_rows
                ]

                approx_rows = tr["approx_rows"]
                tables.append(
                    TableInfo(
                        name=table_name,
                        schema=schema_name,
                        columns=columns,
                        foreign_keys=foreign_keys,
                        indexes=indexes,
                        row_count=max(0, approx_rows) if approx_rows is not None else None,
                        comment=tr["table_comment"],
                    )
                )

        return SchemaInfo(
            tables=tables,
            db_type=self.db_type,
            db_name=self._config.db_name if self._config else "",
        )

    async def test_connection(self) -> bool:
        if not self._pool:
            logger.warning("Postgres test_connection: no pool available")
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("Postgres test_connection failed: %s", exc)
            return False


_PARAM_RE = re.compile(r":(?P<name>\w+)\b")


def _dict_to_positional(query: str, params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Convert :name style params to $N positional params for asyncpg.

    Uses regex with word boundaries to avoid replacing inside string literals
    or partial matches.
    """
    name_to_idx: dict[str, int] = {}
    values: list[Any] = []
    counter = 0

    def _replacer(match: re.Match) -> str:
        nonlocal counter
        name = match.group("name")
        if name not in params:
            return match.group(0)
        if name not in name_to_idx:
            counter += 1
            name_to_idx[name] = counter
            values.append(params[name])
        return f"${name_to_idx[name]}"

    converted = _PARAM_RE.sub(_replacer, query)
    return converted, values
