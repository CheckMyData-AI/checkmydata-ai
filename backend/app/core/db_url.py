"""One answer to "what is the synchronous DSN for this database?".

SQLAlchemy's async URL (``postgresql+asyncpg://…``) is not a libpq DSN, and two places need
the libpq form for different reasons: `PgVectorStore` opens a psycopg pool, and
`run_migrations` opens one connection to hold the migration advisory lock. Keeping the
conversion in one leaf follows the same rule as `core/sql_text.py` and `core/numeric.py` —
one job, one implementation, because the second copy is the one that will not be updated.
"""

from __future__ import annotations


def sync_dsn(url: str) -> str:
    """SQLAlchemy's async URL is not a libpq DSN — psycopg wants the driver gone."""
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def is_postgres(url: str) -> bool:
    """True when *url* points at PostgreSQL, whatever driver it names."""
    return url.startswith(("postgresql", "postgres://"))
