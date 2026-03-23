import json
import logging
import re
import time
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

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
                logger.debug("MongoDB: error closing existing client before reconnect", exc_info=True)
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
                uri += f"{config.db_user}:{config.db_password}@"
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

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        """
        For MongoDB, 'query' is expected to be a JSON string with:
        {"collection": "name", "operation": "find", "filter": {}, ...}
        """
        if not self._db:
            return QueryResult(error="Not connected")

        start = time.monotonic()
        try:
            spec = json.loads(query)
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

            if operation == "find":
                cursor = collection.find(
                    spec.get("filter", {}),
                    spec.get("projection"),
                )
                if "limit" in spec:
                    cursor = cursor.limit(spec["limit"])
                docs = await cursor.to_list(length=spec.get("limit", 1000))
            elif operation == "aggregate":
                cursor = collection.aggregate(spec.get("pipeline", []))
                docs = await cursor.to_list(length=spec.get("limit", 1000))
            elif operation == "count":
                count = await collection.count_documents(spec.get("filter", {}))
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

            for doc in docs:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])

            columns = list(docs[0].keys())
            rows = [list(d.get(c) for c in columns) for d in docs]
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(error=str(e), execution_time_ms=elapsed)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._db:
            return SchemaInfo(db_type=self.db_type)

        tables: list[TableInfo] = []
        collection_names = await self._db.list_collection_names()

        for cname in collection_names:
            coll = self._db[cname]

            # Sample multiple docs for broader field detection
            samples = await coll.find().limit(5).to_list(length=5)
            all_fields: dict[str, str] = {}
            for doc in samples:
                for key, val in doc.items():
                    if key not in all_fields:
                        all_fields[key] = type(val).__name__

            columns = [
                ColumnInfo(
                    name=key,
                    data_type=dtype,
                    is_primary_key=key == "_id",
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

    async def test_connection(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            logger.debug("MongoDB ping failed", exc_info=True)
            return False
