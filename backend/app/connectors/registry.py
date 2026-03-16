from app.connectors.base import BaseConnector
from app.connectors.clickhouse import ClickHouseConnector
from app.connectors.mongodb import MongoDBConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.postgres import PostgresConnector

CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = {
    "postgres": PostgresConnector,
    "postgresql": PostgresConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "mongo": MongoDBConnector,
    "clickhouse": ClickHouseConnector,
}


def get_connector(db_type: str) -> BaseConnector:
    cls = CONNECTOR_REGISTRY.get(db_type.lower())
    if cls is None:
        raise ValueError(f"Unsupported database type: {db_type}. Available: {list(CONNECTOR_REGISTRY.keys())}")
    return cls()
