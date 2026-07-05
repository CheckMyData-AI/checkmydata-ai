import asyncio
import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote_plus

from bson import ObjectId
from bson.decimal128 import Decimal128
from motor.motor_asyncio import AsyncIOMotorClient

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

# R1 C4 (F-CONN-03 / F-CONN-10): read-only enforcement for Mongo query specs.
# Mongo has no transaction-level read-only mode the driver can request, so the
# guard is applied in code before the spec runs. Operator hardening (a read-only
# Mongo user + ``--noscripting``) is the authoritative backstop and is documented
# for deployment; this guard is the app-layer defense.
_MONGO_WRITE_OPS = {
    "insert",
    "update",
    "delete",
    "drop",
    "rename",
    "create_index",
    "drop_index",
    "replace",
}
_MONGO_JS_OPERATORS = ("$where", "$function", "$accumulator")  # server-side JS
_MONGO_WRITE_STAGES = ("$out", "$merge")  # aggregation write stages


def _assert_mongo_read_safe(spec: dict) -> None:
    """Reject write ops, server-side JS, and aggregation write stages.

    Raises ``ValueError`` with a human-readable reason if the spec would write
    to the database or execute server-side JavaScript. Safe (read-only) specs
    return ``None``. Callers translate the ``ValueError`` into a
    ``QueryResult(error=...)`` so a blocked query degrades cleanly rather than
    crashing the request.
    """
    op = spec.get("operation", "find")
    if op in _MONGO_WRITE_OPS:
        raise ValueError(f"Write operation '{op}' not allowed on a read-only connection")
    # Serialize the whole spec so JS operators are caught no matter how deeply
    # they are nested (e.g. inside ``$and`` / ``$expr`` sub-documents).
    blob = json.dumps(spec, default=str)
    for js in _MONGO_JS_OPERATORS:
        if js in blob:
            raise ValueError(f"Server-side JS operator '{js}' not allowed")
    if op == "aggregate":
        for stage in spec.get("pipeline", []):
            if isinstance(stage, dict):
                for w in _MONGO_WRITE_STAGES:
                    if w in stage:
                        raise ValueError(f"Aggregation write stage '{w}' not allowed")


def _infer_fields(
    docs: list[dict[str, Any]],
    max_depth: int = 2,
) -> dict[str, str]:
    """Infer field names and types from a list of sample documents.

    Rules:
    - Scalar values: type name via ``type(val).__name__``.
    - List values: always recorded as ``"array"`` regardless of element types.
    - Dict values: recursed into with a dotted prefix up to *max_depth* levels;
      the parent key itself is NOT emitted as a column (only its leaf children are).
    - ``None`` values are skipped — they do not contribute ``"NoneType"`` to
      the type union.
    - When a field has more than one type across docs, the type names are joined
      as ``"|"``-separated sorted string (e.g. ``"int|str"``), making unions
      deterministic.
    - Depth is measured in dots: ``"a.b"`` has depth 1, ``"a.b.c"`` has depth 2.
      Subtrees deeper than *max_depth* are not emitted.

    Returns a ``{field_path: type_string}`` mapping.
    """
    # field_path -> set of type names seen
    type_sets: dict[str, set[str]] = {}

    def _walk(obj: dict[str, Any], prefix: str, current_depth: int) -> None:
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if val is None:
                # Null — skip rather than polluting the union with NoneType.
                continue
            if isinstance(val, list):
                existing = type_sets.setdefault(path, set())
                existing.add("array")
            elif isinstance(val, dict):
                if current_depth < max_depth:
                    # Recurse into subdocument — parent path is NOT emitted.
                    _walk(val, path, current_depth + 1)
                else:
                    # At depth cap: record the subdoc as a plain "dict" column.
                    existing = type_sets.setdefault(path, set())
                    existing.add("dict")
            else:
                existing = type_sets.setdefault(path, set())
                existing.add(type(val).__name__)

    for doc in docs:
        if isinstance(doc, dict):
            _walk(doc, "", 0)

    return {path: "|".join(sorted(types)) for path, types in type_sets.items()}


def _to_jsonable(value: Any) -> Any:
    """Coerce Mongo-specific BSON types in a result cell to serializable forms.

    Only Mongo-specific types are converted — ``datetime`` and ``bytes`` pass
    through raw to match the SQL connectors, since the response encoder handles
    those uniformly. ``ObjectId`` (which has no SQL analogue) becomes its hex
    string, ``Decimal128`` becomes a ``decimal.Decimal`` (like asyncpg's numeric
    results), and nested documents / arrays are walked so references buried in
    subdocuments are coerced too. Without this, any non-``_id`` ObjectId — e.g.
    a reference field, which is ubiquitous — would reach the response serializer
    as a raw BSON object and break it.
    """
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


class MongoDBConnector(BaseConnector):
    def __init__(self):
        self._client: AsyncIOMotorClient | None = None
        self._db = None
        self._config: ConnectionConfig | None = None

    @property
    def db_type(self) -> str:
        return "mongodb"

    async def connect(self, config: ConnectionConfig) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                logger.debug(
                    "MongoDB: error closing existing client before reconnect", exc_info=True
                )
            self._client = None
            self._db = None
        self._config = config

        if config.connection_string:
            self._client = AsyncIOMotorClient(
                config.connection_string,
                serverSelectionTimeoutMS=10_000,
                connectTimeoutMS=10_000,
                socketTimeoutMS=120_000,
            )
        else:
            host, port = await _tunnel_mgr.get_or_create(config)
            uri = "mongodb://"
            if config.db_user and config.db_password:
                uri += f"{quote_plus(config.db_user)}:{quote_plus(config.db_password)}@"
            uri += f"{host}:{port}/{config.db_name}"
            self._client = AsyncIOMotorClient(
                uri,
                serverSelectionTimeoutMS=10_000,
                connectTimeoutMS=10_000,
                socketTimeoutMS=120_000,
            )

        self._db = self._client[config.db_name]

    async def disconnect(self) -> None:
        if self._client:
            try:
                self._client.close()
            finally:
                self._client = None
                self._db = None

    async def execute_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """
        For MongoDB, 'query' is expected to be a JSON string with:
        {"collection": "name", "operation": "find", "filter": {}, ...}
        """
        if not self._db:
            return QueryResult(error="Not connected")

        from app.connectors.base import resolve_query_timeout

        effective_timeout = resolve_query_timeout(timeout_seconds)
        start = time.monotonic()
        try:
            spec = json.loads(query)
            # R1 C4: block writes / server-side JS on read-only connections.
            # A ValueError here is caught below and returned as QueryResult.error
            # so a blocked query degrades cleanly instead of crashing.
            if self._config and self._config.is_read_only:
                _assert_mongo_read_safe(spec)
            if "collection" not in spec:
                return QueryResult(
                    error="Query spec must include a 'collection' key, e.g. "
                    '{"collection": "my_coll", "operation": "find", "filter": {}}',
                )
            coll_name = spec["collection"]
            valid_coll = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.\-]{0,127}$")
            if not isinstance(coll_name, str) or not valid_coll.match(coll_name):
                return QueryResult(
                    error=f"Invalid collection name: {coll_name!r}",
                )
            collection = self._db[coll_name]
            operation = spec.get("operation", "find")

            from app.connectors.base import MAX_RESULT_ROWS, cap_rows_by_bytes

            # Pull at most ``MAX_RESULT_ROWS + 1`` documents so the +1 sentinel
            # detects our-cap truncation the same way the SQL connectors do.
            # A user-supplied ``limit`` is the requested page (not truncation),
            # so the effective client-side ceiling is bounded by it but never
            # below the safety cap+1 needed to spot more rows than we return.
            user_limit = spec.get("limit")
            if isinstance(user_limit, int) and user_limit >= 0:
                fetch_length = min(user_limit, MAX_RESULT_ROWS) + 1
            else:
                fetch_length = MAX_RESULT_ROWS + 1

            if operation == "find":
                cursor = collection.find(
                    spec.get("filter", {}),
                    spec.get("projection"),
                )
                if isinstance(user_limit, int) and user_limit >= 0:
                    cursor = cursor.limit(user_limit)
                docs = await asyncio.wait_for(
                    cursor.to_list(length=fetch_length), timeout=effective_timeout
                )
            elif operation == "aggregate":
                cursor = collection.aggregate(spec.get("pipeline", []))
                docs = await asyncio.wait_for(
                    cursor.to_list(length=fetch_length), timeout=effective_timeout
                )
            elif operation == "count":
                count = await asyncio.wait_for(
                    collection.count_documents(spec.get("filter", {})),
                    timeout=effective_timeout,
                )
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    columns=["count"],
                    rows=[[count]],
                    row_count=1,
                    execution_time_ms=elapsed,
                )
            else:
                return QueryResult(error=f"Unsupported operation: {operation}")

            elapsed = (time.monotonic() - start) * 1000
            if not docs:
                return QueryResult(row_count=0, execution_time_ms=elapsed)

            # The +1 sentinel: more documents existed than our safety cap allows.
            truncated = len(docs) > MAX_RESULT_ROWS
            capped = docs[:MAX_RESULT_ROWS] if truncated else docs
            columns = list(capped[0].keys()) if capped else []
            # Coerce every cell — not just the top-level _id — so nested or
            # reference ObjectIds / Decimal128 values are serializable.
            rows = [[_to_jsonable(d.get(c)) for c in columns] for d in capped]
            # Bound serialized size like the SQL connectors: a few very wide
            # documents can blow past the byte budget even under the row cap.
            rows, byte_truncated = cap_rows_by_bytes(rows)
            truncated = truncated or byte_truncated
            # Uniform contract (audit-High): ``row_count`` is the number of rows
            # actually returned in ``rows`` (the capped count), matching the SQL
            # connectors — NOT the pre-cap total. ``truncated`` signals more.
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
        if not self._db:
            return SchemaInfo(db_type=self.db_type)

        from app.config import settings

        sample_size: int = getattr(settings, "mongo_schema_sample_size", 100)

        tables: list[TableInfo] = []
        collection_names = await self._db.list_collection_names()

        for cname in collection_names:
            coll = self._db[cname]

            # DBIDX-D11: sample up to mongo_schema_sample_size docs (default 100)
            # and infer field types with union detection and nested path expansion.
            samples = await coll.find().limit(sample_size).to_list(length=sample_size)
            all_fields = _infer_fields(samples)

            columns = [
                ColumnInfo(
                    name=key,
                    data_type=dtype,
                    # PK detection: only the un-dotted top-level "_id" field.
                    is_primary_key=(key == "_id"),
                )
                for key, dtype in all_fields.items()
            ]

            count = await coll.estimated_document_count()

            indexes: list[IndexInfo] = []
            try:
                async for idx in coll.list_indexes():
                    idx_name = idx.get("name", "")
                    idx_keys = list(idx.get("key", {}).keys())
                    is_unique = idx.get("unique", False)
                    indexes.append(
                        IndexInfo(
                            name=idx_name,
                            columns=idx_keys,
                            is_unique=is_unique,
                        )
                    )
            except Exception as exc:
                import logging as _logging

                _logging.getLogger(__name__).debug("Failed to list indexes for %s: %s", cname, exc)

            tables.append(
                TableInfo(
                    name=cname,
                    columns=columns,
                    row_count=count,
                    indexes=indexes,
                )
            )

        return SchemaInfo(
            tables=tables,
            db_type=self.db_type,
            db_name=self._config.db_name if self._config else "",
        )

    async def sample_data(
        self,
        table_name: str,
        limit: int = 3,
    ) -> QueryResult:
        if not self._db:
            return QueryResult(error="Not connected")
        query = json.dumps(
            {
                "collection": table_name,
                "operation": "find",
                "filter": {},
                "limit": limit,
            }
        )
        return await self.execute_query(query)

    _COLL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.\-]{0,127}$")

    async def distinct_values(
        self,
        table: str,
        column: str,
        limit: int = 50,
    ) -> list[str]:
        """Return distinct string values of *column* in *table* via native ``distinct``.

        Uses the motor ``distinct`` command — never builds a SQL string (which would
        be passed to ``execute_query`` where ``json.loads`` would fail). Degrades to
        ``[]`` on any error so callers never receive an exception.
        """
        if not self._db:
            return []
        if not self._COLL_NAME_RE.match(table):
            logger.debug("distinct_values: invalid collection name %r — returning []", table)
            return []
        try:
            collection = self._db[table]
            vals = await collection.distinct(column, {column: {"$ne": None}})
            return [str(_to_jsonable(v)) for v in vals][:limit]
        except Exception:
            logger.debug(
                "distinct_values(%r, %r) failed — returning []", table, column, exc_info=True
            )
            return []

    async def approx_stats(self, table: str, column: str) -> ColumnStats:
        """Return approximate per-column statistics via a native aggregation pipeline.

        The pipeline uses ``$group`` to compute distinct count, null rate, min and max
        in a single server-side pass. A leading ``$limit`` stage bounds the scan on
        large collections. Never builds a SQL string. Degrades to ``ColumnStats()``
        on any error.
        """
        if not self._db:
            return ColumnStats()
        if not self._COLL_NAME_RE.match(table):
            logger.debug("approx_stats: invalid collection name %r — returning empty", table)
            return ColumnStats()
        try:
            from app.config import settings

            sample_cap: int = getattr(settings, "db_index_stats_sample_cap", 100_000)
            col_ref = f"${column}"
            pipeline = [
                {"$limit": sample_cap},
                {
                    "$group": {
                        "_id": None,
                        "distinct": {"$addToSet": col_ref},
                        "nulls": {"$sum": {"$cond": [{"$eq": [col_ref, None]}, 1, 0]}},
                        "total": {"$sum": 1},
                        "min": {"$min": col_ref},
                        "max": {"$max": col_ref},
                    }
                },
            ]
            collection = self._db[table]
            cursor = collection.aggregate(pipeline)
            rows = await cursor.to_list(length=1)
            if not rows:
                return ColumnStats()
            row = rows[0]
            raw_distinct = row.get("distinct")
            if isinstance(raw_distinct, list):
                distinct_count: int | None = len(raw_distinct)
            else:
                distinct_count = int(raw_distinct) if raw_distinct is not None else None
            total = row.get("total") or 0
            nulls = row.get("nulls") or 0
            null_rate = (nulls / total) if total > 0 else None
            return ColumnStats(
                distinct_count=distinct_count,
                null_rate=null_rate,
                min_value=_to_jsonable(row.get("min")),
                max_value=_to_jsonable(row.get("max")),
            )
        except Exception:
            logger.debug(
                "approx_stats(%r, %r) failed — returning empty ColumnStats",
                table,
                column,
                exc_info=True,
            )
            return ColumnStats()

    async def test_connection(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            logger.debug("MongoDB ping failed", exc_info=True)
            return False
