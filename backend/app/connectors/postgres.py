import asyncio
import logging
import re
import time
from typing import Any

import asyncpg

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


def _build_enum_map(
    enum_rows: list[Any],
) -> dict[tuple[str, str, str], list[str]]:
    """Build (schema, table, column) -> sorted label list from pg_enum rows.

    Each row must expose: table_schema, table_name, column_name, label, sortorder.
    Rows may arrive in any order; labels are sorted by sortorder before being stored.
    """
    # Accumulate as (sortorder, label) pairs keyed by (schema, table, col).
    tmp: dict[tuple[str, str, str], list[tuple[float, str]]] = {}
    for row in enum_rows:
        key = (row["table_schema"], row["table_name"], row["column_name"])
        tmp.setdefault(key, []).append((row["sortorder"], row["label"]))
    return {k: [lbl for _, lbl in sorted(pairs)] for k, pairs in tmp.items()}


def _build_check_map(
    check_rows: list[Any],
) -> dict[tuple[str, str], list[str]]:
    """Build (schema, table) -> [check expressions] from pg_constraint rows.

    Each row must expose: table_schema, table_name, expr.
    Order is preserved (insertion order from the query result).
    """
    result: dict[tuple[str, str], list[str]] = {}
    for row in check_rows:
        key = (row["table_schema"], row["table_name"])
        result.setdefault(key, []).append(row["expr"])
    return result


class PostgresConnector(BaseConnector):
    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "postgres"

    async def connect(self, config: ConnectionConfig) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                logger.debug(
                    "Postgres: error closing existing pool before reconnect", exc_info=True
                )
            self._pool = None
        self._config = config

        # R1/C1: enforce read-only at the DB session, not just the app-layer
        # regex. asyncpg applies ``server_settings`` as a server-side SET on
        # every pooled connection, so PG raises "cannot execute ... in a
        # read-only transaction" for any write/DDL. ``None`` is ignored.
        server_settings = {"default_transaction_read_only": "on"} if config.is_read_only else None

        if config.connection_string:
            self._pool = await asyncpg.create_pool(
                config.connection_string,
                min_size=1,
                max_size=5,
                command_timeout=settings.query_timeout_seconds,
                server_settings=server_settings,
            )
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
                command_timeout=settings.query_timeout_seconds,
                server_settings=server_settings,
            )

    async def disconnect(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            finally:
                self._pool = None

    async def execute_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        if not self._pool:
            return QueryResult(error="Not connected")

        start = time.monotonic()
        from app.connectors.base import MAX_RESULT_ROWS

        if params:
            numbered_query, values = _dict_to_positional(query, params)
        else:
            numbered_query, values = query, []

        pool = self._pool

        async def _run() -> list:
            conn = await pool.acquire()
            try:
                if _is_row_returning(numbered_query):
                    # R2-1: stream via a server-side cursor and pull at most
                    # ``MAX_RESULT_ROWS + 1`` rows. The +1 sentinel detects
                    # truncation without materialising the entire (potentially
                    # millions-of-rows) result set in memory. asyncpg requires
                    # non-scrollable cursors to live inside a transaction.
                    async with conn.transaction():
                        cur = await conn.cursor(numbered_query, *values)
                        return await cur.fetch(MAX_RESULT_ROWS + 1)
                # Non-row-returning statements (DDL/DML) can't use a cursor.
                return await conn.fetch(numbered_query, *values)
            except (asyncio.CancelledError, TimeoutError):
                # Re-audit fix: ``asyncio.wait_for`` below cancels this coroutine
                # mid-cursor / mid-transaction on timeout. A connection
                # interrupted that way may still be draining the server-side
                # cursor or holding an open transaction, so returning it to the
                # asyncpg pool would hand the next caller a poisoned connection.
                # Terminate it (sync, immediate transport close) so the pool
                # discards it on release and reconnects fresh next time.
                try:
                    conn.terminate()
                except Exception:
                    logger.debug(
                        "Postgres: terminate on timed-out connection failed", exc_info=True
                    )
                raise
            finally:
                await pool.release(conn)

        from app.connectors.base import resolve_query_timeout

        timeout_s = resolve_query_timeout(timeout_seconds)
        try:
            # R1-5: bound the whole operation (pool acquire + query) with an
            # explicit wait_for, matching the mysql/clickhouse connectors.
            # asyncpg's pool ``command_timeout`` only covers a single command,
            # not a hung pool acquire or multi-step cursor read.
            rows = await asyncio.wait_for(_run(), timeout=timeout_s)

            elapsed = (time.monotonic() - start) * 1000
            if not rows:
                return QueryResult(row_count=0, execution_time_ms=elapsed)

            columns = list(rows[0].keys())
            truncated = len(rows) > MAX_RESULT_ROWS
            capped = rows[:MAX_RESULT_ROWS] if truncated else rows
            data = [list(r.values()) for r in capped]
            # Byte-level backstop alongside the row cap (wide rows / BLOBs).
            from app.connectors.base import cap_rows_by_bytes

            data, byte_truncated = cap_rows_by_bytes(data)
            truncated = truncated or byte_truncated
            # When truncated we only know "> MAX_RESULT_ROWS"; report the
            # returned count and rely on ``truncated`` to signal more.
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
                error=f"Query timed out after {timeout_s:g}s",
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

        _excluded = ("pg_catalog", "information_schema")
        tables: list[TableInfo] = []
        async with self._pool.acquire() as conn:
            # 1) All tables (already bulk)
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

            # 2) All columns in one bulk query
            all_col_rows = await conn.fetch(
                """
                SELECT c.table_schema, c.table_name,
                       c.column_name, c.data_type, c.is_nullable, c.column_default,
                       pgd.description AS column_comment
                FROM information_schema.columns c
                LEFT JOIN pg_catalog.pg_statio_all_tables st
                    ON st.schemaname = c.table_schema AND st.relname = c.table_name
                LEFT JOIN pg_catalog.pg_description pgd
                    ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
                WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
                """
            )
            col_map: dict[tuple[str, str], list[dict]] = {}
            for c in all_col_rows:
                key = (c["table_schema"], c["table_name"])
                col_map.setdefault(key, []).append(c)

            # 3) All PKs in one bulk query
            all_pk_rows = await conn.fetch(
                """
                SELECT n.nspname AS table_schema, c.relname AS table_name,
                       a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE i.indisprimary AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                """
            )
            pk_map: dict[tuple[str, str], set[str]] = {}
            for r in all_pk_rows:
                key = (r["table_schema"], r["table_name"])
                pk_map.setdefault(key, set()).add(r["attname"])

            # 4) All FKs in one bulk query
            all_fk_rows = await conn.fetch(
                """
                SELECT
                    ns.nspname AS table_schema,
                    cl_child.relname AS table_name,
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
                WHERE con.contype = 'f'
                  AND ns.nspname NOT IN ('pg_catalog', 'information_schema')
                """
            )
            fk_map: dict[tuple[str, str], list[ForeignKeyInfo]] = {}
            for fk in all_fk_rows:
                key = (fk["table_schema"], fk["table_name"])
                fk_map.setdefault(key, []).append(
                    ForeignKeyInfo(
                        column=fk["column_name"],
                        references_table=fk["references_table"],
                        references_column=fk["references_column"],
                    )
                )

            # 5) All indexes in one bulk query
            # (numbered 5 in the original; enum + check are 6 and 7)
            all_idx_rows = await conn.fetch(
                """
                SELECT ns.nspname AS table_schema, tc.relname AS table_name,
                       ic.relname AS index_name, i.indisunique,
                       array_agg(a.attname ORDER BY k.n) AS columns
                FROM pg_index i
                JOIN pg_class ic ON ic.oid = i.indexrelid
                JOIN pg_class tc ON tc.oid = i.indrelid
                JOIN pg_namespace ns ON ns.oid = tc.relnamespace
                CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, n)
                JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = k.attnum
                WHERE NOT i.indisprimary
                  AND ns.nspname NOT IN ('pg_catalog', 'information_schema')
                GROUP BY ns.nspname, tc.relname, ic.relname, i.indisunique
                """
            )
            idx_map: dict[tuple[str, str], list[IndexInfo]] = {}
            for ir in all_idx_rows:
                key = (ir["table_schema"], ir["table_name"])
                idx_map.setdefault(key, []).append(
                    IndexInfo(
                        name=ir["index_name"],
                        columns=list(ir["columns"]),
                        is_unique=ir["indisunique"],
                    )
                )

            # 6) Enum labels — one row per (schema, table, column, label)
            all_enum_rows = await conn.fetch(
                """
                SELECT n.nspname  AS table_schema,
                       c.relname  AS table_name,
                       a.attname  AS column_name,
                       e.enumlabel     AS label,
                       e.enumsortorder AS sortorder
                FROM pg_attribute a
                JOIN pg_class     c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_type      t ON t.oid = a.atttypid
                JOIN pg_enum      e ON e.enumtypid = t.oid
                WHERE t.typtype = 'e'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY n.nspname, c.relname, a.attname, e.enumsortorder
                """
            )
            enum_map = _build_enum_map(list(all_enum_rows))

            # 7) CHECK constraints — one row per (schema, table, constraint)
            all_check_rows = await conn.fetch(
                """
                SELECT n.nspname  AS table_schema,
                       cl.relname AS table_name,
                       pg_get_constraintdef(con.oid) AS expr
                FROM pg_constraint con
                JOIN pg_class     cl ON cl.oid = con.conrelid
                JOIN pg_namespace n  ON n.oid  = cl.relnamespace
                WHERE con.contype = 'c'
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                """
            )
            check_map = _build_check_map(list(all_check_rows))

            # Assemble TableInfo objects
            for tr in table_rows:
                schema_name = tr["table_schema"]
                table_name = tr["table_name"]
                key = (schema_name, table_name)

                pk_names = pk_map.get(key, set())
                col_rows = col_map.get(key, [])

                # Distribute table-level CHECK expressions to the first column
                # name that appears as a word token inside each expression.
                col_names = [c["column_name"] for c in col_rows]
                table_checks = check_map.get(key, [])
                # col_check_map: column_name -> [check exprs that mention it first]
                col_check_map: dict[str, list[str]] = {}
                for expr in table_checks:
                    for col_name in col_names:
                        if re.search(r"\b" + re.escape(col_name) + r"\b", expr):
                            col_check_map.setdefault(col_name, []).append(expr)
                            break
                    # if no column matched, the expression is silently skipped per brief

                columns = [
                    ColumnInfo(
                        name=c["column_name"],
                        data_type=c["data_type"],
                        is_nullable=c["is_nullable"] == "YES",
                        is_primary_key=c["column_name"] in pk_names,
                        default=c["column_default"],
                        comment=c["column_comment"],
                        enum_labels=enum_map.get((schema_name, table_name, c["column_name"])),
                        check_constraints=col_check_map.get(c["column_name"], []),
                    )
                    for c in col_rows
                ]

                approx_rows = tr["approx_rows"]
                tables.append(
                    TableInfo(
                        name=table_name,
                        schema=schema_name,
                        columns=columns,
                        foreign_keys=fk_map.get(key, []),
                        indexes=idx_map.get(key, []),
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

# Leading SQL comments to strip before sniffing the first keyword.
_LEADING_COMMENT_RE = re.compile(r"^\s*(?:--[^\n]*\n|/\*.*?\*/\s*)", re.DOTALL)
_ROW_RETURNING_RE = re.compile(
    r"^\s*(?:WITH|SELECT|VALUES|TABLE|SHOW|EXPLAIN)\b",
    re.IGNORECASE,
)


def _is_row_returning(query: str) -> bool:
    """Heuristic: does this statement return a result set (cursor-compatible)?

    asyncpg server-side cursors only work for row-returning statements; DDL/DML
    must use ``fetch``/``execute``. We strip leading comments, then match the
    first keyword. ``WITH`` is included because CTEs commonly wrap a SELECT
    (a ``WITH ... DELETE`` is rare in analytics workloads and degrades safely
    to the cursor path raising, which is caught and surfaced as an error).
    """
    stripped = query
    # Strip any stack of leading comments.
    while True:
        m = _LEADING_COMMENT_RE.match(stripped)
        if not m:
            break
        stripped = stripped[m.end() :]
    return bool(_ROW_RETURNING_RE.match(stripped))


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
