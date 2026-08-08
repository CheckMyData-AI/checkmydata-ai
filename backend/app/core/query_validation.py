"""Data models for the query validation and self-healing loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.connectors.base import QueryResult

# The vocabulary moved to a leaf module so `app.connectors.base` can name an error
# type without importing this one (which imports *it*). Re-exported here so every
# existing `from app.core.query_validation import QueryErrorType` keeps working.
from app.core.error_types import NON_RETRYABLE_ERRORS, QueryErrorType

__all__ = [
    "NON_RETRYABLE_ERRORS",
    "QueryAttempt",
    "QueryError",
    "QueryErrorType",
    "ValidationConfig",
    "ValidationLoopResult",
    "ValidationResult",
]


@dataclass
class QueryError:
    error_type: QueryErrorType
    message: str
    raw_error: str
    is_retryable: bool = True
    suggested_tables: list[str] = field(default_factory=list)
    suggested_columns: list[str] = field(default_factory=list)
    schema_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type.value,
            "message": self.message,
            "raw_error": self.raw_error,
            "is_retryable": self.is_retryable,
            "suggested_tables": self.suggested_tables,
            "suggested_columns": self.suggested_columns,
        }


@dataclass
class ValidationResult:
    is_valid: bool
    error: QueryError | None = None
    warnings: list[str] = field(default_factory=list)
    # SYNC-L1: single user-facing warning for degrade-not-die path (filter guard).
    # Distinct from the list-valued ``warnings`` used by other validators so the
    # guard can carry a rich message without touching caller list-extend logic.
    warning: str | None = None


@dataclass
class QueryAttempt:
    attempt_number: int
    query: str
    explanation: str
    error: QueryError | None = None
    results: QueryResult | None = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt_number,
            "query": self.query,
            "explanation": self.explanation,
            "error": self.error.message if self.error else None,
            "error_type": self.error.error_type.value if self.error else None,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class ValidationLoopResult:
    success: bool
    query: str
    explanation: str
    results: QueryResult | None = None
    attempts: list[QueryAttempt] = field(default_factory=list)
    total_attempts: int = 0
    final_error: QueryError | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationConfig:
    max_retries: int = 3
    enable_explain: bool = True
    enable_schema_validation: bool = True
    empty_result_retry: bool = False
    explain_row_warning_threshold: int = 100_000
    query_timeout_seconds: int = 30
