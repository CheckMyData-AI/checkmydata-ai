"""Query-error vocabulary, in a leaf module both layers can import.

This lives apart from :mod:`app.core.query_validation` for one structural reason:
``query_validation`` imports ``QueryResult`` from :mod:`app.connectors.base`, so the
dependency runs **core -> connectors**. Connectors need to *name* an error type when
they build a ``QueryResult`` — a timeout in particular, because ``asyncio.wait_for``
raises a builtin ``TimeoutError`` that carries no message, leaving the connector with
nothing but a hand-written string to pass upward. Importing the enum back from
``query_validation`` would close that loop into a cycle.

**This module must not import anything from ``app``.** That is the whole contract, and
``tests/unit/test_connector_timeout_type.py`` asserts it.
"""

from __future__ import annotations

from enum import StrEnum


class QueryErrorType(StrEnum):
    COLUMN_NOT_FOUND = "column_not_found"
    TABLE_NOT_FOUND = "table_not_found"
    SYNTAX_ERROR = "syntax_error"
    TYPE_MISMATCH = "type_mismatch"
    AMBIGUOUS_COLUMN = "ambiguous_column"
    PERMISSION_DENIED = "permission_denied"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    COLLATION_MISMATCH = "collation_mismatch"
    GROUP_BY_VIOLATION = "group_by_violation"
    EMPTY_RESULT = "empty_result"
    EXPLAIN_WARNING = "explain_warning"
    UNKNOWN = "unknown"


NON_RETRYABLE_ERRORS = frozenset(
    {
        QueryErrorType.PERMISSION_DENIED,
    }
)
# A connection error is usually transient (DB momentarily unavailable, network
# blip) — it is NOT a query problem. ValidationLoop retries it by re-running the
# same query after a backoff (no LLM repair), so it is deliberately retryable
# rather than listed in NON_RETRYABLE_ERRORS.
#
# TIMEOUT is likewise absent, but for a different reason and with different
# handling: re-running the *same* query after a sub-second backoff cannot beat a
# 30-second timeout. ValidationLoop gives it exactly one narrowing repair and then
# stops as `transient` — see the timeout budget there.
