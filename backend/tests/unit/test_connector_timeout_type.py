"""A query timeout must reach the classifier as a *type*, not as prose.

`asyncio.wait_for` raises the builtin `TimeoutError`, and that exception carries no
message at all (`repr()` is `TimeoutError()`, Python 3.12). Each connector therefore
synthesises `"Query timed out after Ns"` into `QueryResult.error`. Before this change
that string was the only signal, and `ErrorClassifier` — whose TIMEOUT patterns match
only *vendor*-worded timeouts — fell through to `UNKNOWN` with `is_retryable=True`,
handing a dead database to the LLM query repairer as though the SQL were at fault.

These tests pin the contract that removes the guesswork: every connector reports
`QueryResult.error_type is QueryErrorType.TIMEOUT`, while keeping the human-readable
`error` string for logs and for the message the user eventually sees.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.connectors.base import QueryResult
from app.core.error_types import QueryErrorType


async def _raise_timeout(awaitable: Any = None, *_args: Any, **_kwargs: Any) -> Any:
    """Stand-in for `asyncio.wait_for` that always expires.

    The real `wait_for` consumes the awaitable it is handed; closing it keeps the
    connectors' inner coroutines from raising "never awaited" warnings that would
    otherwise be mistaken for a defect in this change.
    """
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()
    raise TimeoutError


@pytest.fixture
def expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every `asyncio.wait_for` in the process expire immediately."""
    monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)


async def test_mysql_timeout_is_typed(expired: None) -> None:
    from app.connectors.mysql import MySQLConnector

    adapter = MySQLConnector()
    adapter._pool = object()  # only truthiness is checked before the timeout

    result = await adapter.execute_query("SELECT 1")

    assert result.error_type is QueryErrorType.TIMEOUT
    assert result.error and "timed out" in result.error


async def test_postgres_timeout_is_typed(expired: None) -> None:
    from app.connectors.postgres import PostgresConnector

    adapter = PostgresConnector()
    adapter._pool = object()

    result = await adapter.execute_query("SELECT 1")

    assert result.error_type is QueryErrorType.TIMEOUT
    assert result.error and "timed out" in result.error


async def test_clickhouse_timeout_is_typed(expired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.connectors.clickhouse import ClickHouseConnector

    adapter = ClickHouseConnector()

    async def _client() -> object:
        return object()

    reset_calls: list[bool] = []

    async def _reset() -> None:
        reset_calls.append(True)

    monkeypatch.setattr(adapter, "_get_client", _client)
    monkeypatch.setattr(adapter, "_reset_client", _reset)

    result = await adapter.execute_query("SELECT 1")

    assert result.error_type is QueryErrorType.TIMEOUT
    assert result.error and "timed out" in result.error
    # Audit fix B2 must survive this change: a cancelled coroutine leaves the HTTP
    # worker thread holding the session, so the poisoned client is always dropped.
    assert reset_calls == [True]


async def test_mongodb_timeout_is_typed(expired: None) -> None:
    from app.connectors.mongodb import MongoDBConnector

    class _Cursor:
        def limit(self, _n: int) -> _Cursor:
            return self

        def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
            return []  # a plain value: `wait_for` is patched and never awaits it

    class _Collection:
        def find(self, *_a: Any, **_k: Any) -> _Cursor:
            return _Cursor()

    adapter = MongoDBConnector()
    adapter._db = {"c": _Collection()}  # only the `is None` guard runs before the timeout

    result = await adapter.execute_query(
        json.dumps({"collection": "c", "operation": "find", "filter": {}})
    )

    assert result.error_type is QueryErrorType.TIMEOUT
    assert result.error and "timed out" in result.error


def test_query_result_error_type_defaults_to_none() -> None:
    """The field is additive: a connector that never sets it is unimproved, not broken."""
    assert QueryResult().error_type is None
    assert QueryResult(error="boom").error_type is None


def test_error_types_module_imports_nothing_from_app() -> None:
    """`error_types` is a leaf so both `app.core` and `app.connectors` can import it.

    `app.core.query_validation` imports `QueryResult` from `app.connectors.base`, so the
    dependency runs core -> connectors. If the enum lived in `query_validation`, having
    `base.py` import it would close that loop into a cycle.
    """
    from pathlib import Path

    import app.core.error_types as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    offending = [
        line for line in source.splitlines() if line.startswith(("import app", "from app"))
    ]
    assert not offending, f"error_types must not import from app: {offending}"
