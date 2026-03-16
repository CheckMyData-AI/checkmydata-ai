"""EXPLAIN dry-run validator — runs EXPLAIN to catch errors before execution."""

from __future__ import annotations

import json
import logging

from app.connectors.base import BaseConnector
from app.core.error_classifier import ErrorClassifier
from app.core.query_validation import ValidationResult

logger = logging.getLogger(__name__)

_classifier = ErrorClassifier()


class ExplainValidator:
    """Runs EXPLAIN on a query to validate it without executing."""

    def __init__(self, row_warning_threshold: int = 100_000):
        self._row_threshold = row_warning_threshold

    async def validate(
        self,
        connector: BaseConnector,
        query: str,
        db_type: str,
    ) -> ValidationResult:
        if db_type.lower() in {"mongodb", "mongo"}:
            return ValidationResult(is_valid=True)

        explain_query = self._build_explain_query(query, db_type)
        if not explain_query:
            return ValidationResult(is_valid=True)

        try:
            result = await connector.execute_query(explain_query)
        except Exception as exc:
            logger.warning("EXPLAIN failed with exception: %s", exc)
            classified = _classifier.classify(str(exc), db_type)
            return ValidationResult(is_valid=False, error=classified)

        if result.error:
            classified = _classifier.classify(result.error, db_type)
            return ValidationResult(is_valid=False, error=classified)

        warnings = self._analyze_plan(result, db_type)
        return ValidationResult(is_valid=True, warnings=warnings)

    @staticmethod
    def _build_explain_query(query: str, db_type: str) -> str | None:
        dt = db_type.lower()
        stripped = query.strip().rstrip(";")
        if dt in {"postgresql", "postgres"}:
            return f"EXPLAIN (FORMAT JSON) {stripped}"
        if dt == "mysql":
            return f"EXPLAIN {stripped}"
        if dt == "clickhouse":
            return f"EXPLAIN {stripped}"
        return None

    def _analyze_plan(self, result, db_type: str) -> list[str]:
        warnings: list[str] = []
        dt = db_type.lower()

        try:
            if dt in {"postgresql", "postgres"}:
                warnings.extend(self._analyze_pg(result))
            elif dt == "mysql":
                warnings.extend(self._analyze_mysql(result))
        except Exception as exc:
            logger.debug("EXPLAIN plan analysis failed: %s", exc)

        return warnings

    def _analyze_pg(self, result) -> list[str]:
        warnings: list[str] = []
        if not result.rows:
            return warnings

        try:
            raw = result.rows[0][0]
            plan_data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(plan_data, list) and plan_data:
                plan_data = plan_data[0]
            plan = plan_data.get("Plan", plan_data)
            self._walk_pg_plan(plan, warnings)
        except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
            pass
        return warnings

    def _walk_pg_plan(self, node: dict, warnings: list[str]) -> None:
        node_type = node.get("Node Type", "")
        rows = node.get("Plan Rows", 0)

        if node_type == "Seq Scan" and rows > self._row_threshold:
            table = node.get("Relation Name", "?")
            warnings.append(
                f"Sequential scan on '{table}' (~{rows:,} rows). "
                f"Consider adding an index."
            )

        for child in node.get("Plans", []):
            self._walk_pg_plan(child, warnings)

    def _analyze_mysql(self, result) -> list[str]:
        warnings: list[str] = []
        if not result.rows:
            return warnings

        col_names = [c.lower() for c in result.columns]
        type_idx = col_names.index("type") if "type" in col_names else None
        rows_idx = col_names.index("rows") if "rows" in col_names else None
        table_idx = col_names.index("table") if "table" in col_names else None

        if type_idx is None or rows_idx is None:
            return warnings

        for row in result.rows:
            scan_type = str(row[type_idx]).upper() if row[type_idx] else ""
            est_rows = int(row[rows_idx]) if row[rows_idx] else 0
            table_name = row[table_idx] if table_idx is not None else "?"

            if scan_type == "ALL" and est_rows > self._row_threshold:
                warnings.append(
                    f"Full table scan on '{table_name}' (~{est_rows:,} rows). "
                    f"Consider adding an index."
                )

        return warnings
