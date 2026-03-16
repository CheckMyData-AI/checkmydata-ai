import json
import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyLevel(str, Enum):
    READ_ONLY = "read_only"
    ALLOW_DML = "allow_dml"
    UNRESTRICTED = "unrestricted"


DANGEROUS_PATTERNS_SQL = [
    re.compile(r"\b(DROP)\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b", re.IGNORECASE),
    re.compile(r"\b(TRUNCATE)\s+", re.IGNORECASE),
    re.compile(r"\b(ALTER)\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\b(GRANT|REVOKE)\s+", re.IGNORECASE),
    re.compile(r"\b(CREATE)\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW|USER|ROLE)\b", re.IGNORECASE),
]

DML_PATTERNS_SQL = [
    re.compile(r"\b(INSERT)\s+INTO\b", re.IGNORECASE),
    re.compile(r"\b(UPDATE)\s+\w+\s+SET\b", re.IGNORECASE),
    re.compile(r"\b(DELETE)\s+FROM\b", re.IGNORECASE),
]


@dataclass
class SafetyResult:
    is_safe: bool
    reason: str = ""
    query: str = ""


class SafetyGuard:
    """Validates queries against a configurable safety level."""

    def __init__(self, level: SafetyLevel = SafetyLevel.READ_ONLY):
        self.level = level

    def validate_sql(self, query: str) -> SafetyResult:
        stripped = query.strip().rstrip(";")

        for pattern in DANGEROUS_PATTERNS_SQL:
            if pattern.search(stripped):
                match_text = pattern.search(stripped).group(0)  # type: ignore[union-attr]
                return SafetyResult(
                    is_safe=False,
                    reason=f"Blocked dangerous operation: {match_text}",
                    query=query,
                )

        if self.level == SafetyLevel.READ_ONLY:
            for pattern in DML_PATTERNS_SQL:
                if pattern.search(stripped):
                    match_text = pattern.search(stripped).group(0)  # type: ignore[union-attr]
                    return SafetyResult(
                        is_safe=False,
                        reason=f"DML not allowed in read-only mode: {match_text}",
                        query=query,
                    )

        return SafetyResult(is_safe=True, query=query)

    def validate_mongo(self, query: str) -> SafetyResult:
        """For MongoDB JSON queries, block write operations."""
        try:
            spec = json.loads(query)
        except json.JSONDecodeError:
            return SafetyResult(is_safe=False, reason="Invalid JSON query", query=query)

        operation = spec.get("operation", "find")
        write_ops = {"insert", "update", "delete", "drop", "rename", "create_index", "drop_index"}

        if self.level == SafetyLevel.READ_ONLY and operation in write_ops:
            return SafetyResult(
                is_safe=False,
                reason=f"Write operation '{operation}' not allowed in read-only mode",
                query=query,
            )

        return SafetyResult(is_safe=True, query=query)

    def validate(self, query: str, db_type: str) -> SafetyResult:
        if self.level == SafetyLevel.UNRESTRICTED:
            return SafetyResult(is_safe=True, query=query)

        if db_type in {"mongodb", "mongo"}:
            return self.validate_mongo(query)
        return self.validate_sql(query)
