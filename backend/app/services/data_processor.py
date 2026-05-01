"""DataProcessor — in-memory enrichment of QueryResult rows.

Applies registered transformation operations (e.g. IP-to-country,
phone-to-country, in-memory aggregation) to ``QueryResult`` objects so the
orchestrator can enrich data between query steps without going back to the
database.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.connectors.base import QueryResult
from app.services.geoip_service import GeoIPService, get_geoip_service
from app.services.phone_country_service import PhoneCountryService, get_phone_country_service

logger = logging.getLogger(__name__)


@dataclass
class ProcessedData:
    """Result of a data processing operation."""

    query_result: QueryResult
    summary: str


SUPPORTED_OPERATIONS = (
    "ip_to_country",
    "phone_to_country",
    "aggregate_data",
    "filter_data",
)

_AGG_FUNCTIONS = {"count", "count_distinct", "sum", "avg", "min", "max", "median"}


class DataProcessor:
    """Applies data-enrichment operations to a ``QueryResult``."""

    def __init__(
        self,
        geoip: GeoIPService | None = None,
        phone_svc: PhoneCountryService | None = None,
    ) -> None:
        self._geoip = geoip or get_geoip_service()
        self._phone = phone_svc or get_phone_country_service()

    def process(
        self,
        query_result: QueryResult,
        operation: str,
        params: dict[str, Any],
    ) -> ProcessedData:
        """Dispatch *operation* on *query_result*.

        Raises ``ValueError`` for unknown operations or missing params.
        """
        if operation == "ip_to_country":
            return self._ip_to_country(query_result, params)
        if operation == "phone_to_country":
            return self._phone_to_country(query_result, params)
        if operation == "aggregate_data":
            return self._aggregate_data(query_result, params)
        if operation == "filter_data":
            return self._filter_data(query_result, params)
        raise ValueError(
            f"Unknown operation '{operation}'. Supported: {', '.join(SUPPORTED_OPERATIONS)}"
        )

    # ------------------------------------------------------------------
    # ip_to_country
    # ------------------------------------------------------------------

    def _ip_to_country(
        self,
        qr: QueryResult,
        params: dict[str, Any],
    ) -> ProcessedData:
        column: str = params.get("column", "")
        if not column:
            raise ValueError("ip_to_country requires a 'column' parameter")

        if column not in qr.columns:
            raise ValueError(
                f"Column '{column}' not found in result. Available columns: {', '.join(qr.columns)}"
            )

        col_idx = qr.columns.index(column)
        cc_col = f"{column}_country_code"
        cn_col = f"{column}_country_name"

        # T18: dedup lookups so an IP that appears 10,000 times is resolved
        # once. Huge win on large datasets where a handful of IPs dominate.
        unique_ips: set[str] = set()
        for row in qr.rows:
            unique_ips.add(str(row[col_idx]) if row[col_idx] is not None else "")

        ip_cache: dict[str, tuple[str, str]] = {}
        for ip_val in unique_ips:
            geo = self._geoip.lookup(ip_val)
            ip_cache[ip_val] = (geo.country_code, geo.country_name)

        new_columns = [*qr.columns, cc_col, cn_col]
        new_rows: list[list[Any]] = []
        country_stats: dict[str, int] = {}

        for row in qr.rows:
            ip_val = str(row[col_idx]) if row[col_idx] is not None else ""
            cc, cn = ip_cache.get(ip_val, ("", ""))
            new_rows.append([*row, cc, cn])
            label = cc or "Unknown"
            country_stats[label] = country_stats.get(label, 0) + 1

        enriched = QueryResult(
            columns=new_columns,
            rows=new_rows,
            row_count=qr.row_count,
            execution_time_ms=qr.execution_time_ms,
            error=qr.error,
            truncated=qr.truncated,
        )

        top = sorted(country_stats.items(), key=lambda kv: kv[1], reverse=True)[:10]
        stats_lines = [f"  {cc}: {cnt} rows" for cc, cnt in top]
        summary = (
            f"Added columns '{cc_col}' and '{cn_col}' from column '{column}'.\n"
            f"Resolved {len(new_rows)} IP addresses ({len(unique_ips)} unique).\n"
            f"Top countries:\n" + "\n".join(stats_lines)
        )

        return ProcessedData(query_result=enriched, summary=summary)

    # ------------------------------------------------------------------
    # phone_to_country
    # ------------------------------------------------------------------

    def _phone_to_country(
        self,
        qr: QueryResult,
        params: dict[str, Any],
    ) -> ProcessedData:
        column: str = params.get("column", "")
        if not column:
            raise ValueError("phone_to_country requires a 'column' parameter")

        if column not in qr.columns:
            raise ValueError(
                f"Column '{column}' not found in result. Available columns: {', '.join(qr.columns)}"
            )

        col_idx = qr.columns.index(column)
        cc_col = f"{column}_country_code"
        cn_col = f"{column}_country_name"

        # T18: dedup lookups — a customer list often has many duplicates.
        unique_phones: set[str] = set()
        for row in qr.rows:
            unique_phones.add(str(row[col_idx]) if row[col_idx] is not None else "")

        phone_cache: dict[str, tuple[str, str]] = {}
        for phone_val in unique_phones:
            res = self._phone.lookup(phone_val)
            phone_cache[phone_val] = (res.country_code, res.country_name)

        new_columns = [*qr.columns, cc_col, cn_col]
        new_rows: list[list[Any]] = []
        country_stats: dict[str, int] = {}

        for row in qr.rows:
            phone_val = str(row[col_idx]) if row[col_idx] is not None else ""
            cc, cn = phone_cache.get(phone_val, ("", ""))
            new_rows.append([*row, cc, cn])
            label = cc or "Unknown"
            country_stats[label] = country_stats.get(label, 0) + 1

        enriched = QueryResult(
            columns=new_columns,
            rows=new_rows,
            row_count=qr.row_count,
            execution_time_ms=qr.execution_time_ms,
            error=qr.error,
            truncated=qr.truncated,
        )

        top = sorted(country_stats.items(), key=lambda kv: kv[1], reverse=True)[:10]
        stats_lines = [f"  {cc}: {cnt} rows" for cc, cnt in top]
        summary = (
            f"Added columns '{cc_col}' and '{cn_col}' from column '{column}'.\n"
            f"Resolved {len(new_rows)} phone numbers to countries "
            f"({len(unique_phones)} unique).\n"
            f"Top countries:\n" + "\n".join(stats_lines)
        )

        return ProcessedData(query_result=enriched, summary=summary)

    # ------------------------------------------------------------------
    # aggregate_data
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_aggregations(
        raw: Any,
    ) -> list[tuple[str, str]]:
        """Accept both legacy ``dict`` and new ``list`` aggregation formats.

        Returns a list of ``(column, function)`` tuples — duplicates allowed.
        """
        if isinstance(raw, list):
            return [(str(c), str(f)) for c, f in raw]
        if isinstance(raw, dict):
            return list(raw.items())
        return []

    def _aggregate_data(
        self,
        qr: QueryResult,
        params: dict[str, Any],
    ) -> ProcessedData:
        group_by: list[str] = params.get("group_by", [])
        raw_aggs = params.get("aggregations", [])
        agg_pairs = self._normalize_aggregations(raw_aggs)
        sort_by: str = params.get("sort_by", "")
        order: str = params.get("order", "asc").lower()

        if not group_by:
            raise ValueError("aggregate_data requires a non-empty 'group_by' list")
        if not agg_pairs:
            raise ValueError("aggregate_data requires a non-empty 'aggregations' list")

        col_index = {c: i for i, c in enumerate(qr.columns)}
        for col in group_by:
            if col not in col_index:
                raise ValueError(
                    f"group_by column '{col}' not found. Available: {', '.join(qr.columns)}"
                )
        for col, fn in agg_pairs:
            fn_lower = fn.lower()
            if fn_lower not in _AGG_FUNCTIONS:
                raise ValueError(
                    f"Unsupported aggregation '{fn}' for column '{col}'. "
                    f"Supported: {', '.join(sorted(_AGG_FUNCTIONS))}"
                )
            if fn_lower == "count_distinct" and col == "*":
                raise ValueError("count_distinct requires a column name, not '*'")
            if col != "*" and col not in col_index:
                raise ValueError(
                    f"Aggregation column '{col}' not found. Available: {', '.join(qr.columns)}"
                )

        group_indices = [col_index[c] for c in group_by]

        groups: dict[tuple[Any, ...], list[list[Any]]] = defaultdict(list)
        for row in qr.rows:
            key = tuple(row[i] for i in group_indices)
            groups[key].append(row)

        result_columns: list[str] = list(group_by)
        agg_specs: list[tuple[str, str, int | None]] = []
        for col, fn in agg_pairs:
            fn_lower = fn.lower()
            col_i = col_index.get(col) if col != "*" else None
            label = f"{fn_lower}_{col}" if col != "*" else f"{fn_lower}_all"
            result_columns.append(label)
            agg_specs.append((fn_lower, col, col_i))

        result_rows: list[list[Any]] = []
        for key, rows in groups.items():
            result_row: list[Any] = list(key)
            for fn_lower, _col, col_i in agg_specs:
                result_row.append(self._compute_agg(fn_lower, col_i, rows))
            result_rows.append(result_row)

        if sort_by:
            if sort_by not in result_columns:
                raise ValueError(
                    f"sort_by column '{sort_by}' not in result columns. "
                    f"Available: {', '.join(result_columns)}"
                )
            sort_idx = result_columns.index(sort_by)
            reverse = order == "desc"
            result_rows.sort(
                key=lambda r: (r[sort_idx] is None, r[sort_idx]),
                reverse=reverse,
            )
        else:
            result_rows.sort(key=lambda r: r[: len(group_by)])

        agg_qr = QueryResult(
            columns=result_columns,
            rows=result_rows,
            row_count=len(result_rows),
            execution_time_ms=qr.execution_time_ms,
        )

        summary = (
            f"Aggregated {len(qr.rows)} rows into {len(result_rows)} groups "
            f"by {', '.join(group_by)}. "
            f"Computed: {', '.join(f'{fn}({c})' for c, fn in agg_pairs)}."
        )

        return ProcessedData(query_result=agg_qr, summary=summary)

    @staticmethod
    def _compute_agg(fn: str, col_i: int | None, rows: list[list[Any]]) -> Any:
        """Compute a single aggregation value."""
        if fn == "count":
            return len(rows)

        if fn == "count_distinct":
            if col_i is None:
                return len(rows)
            return len({r[col_i] for r in rows if r[col_i] is not None})

        if col_i is None:
            return len(rows)

        values = []
        for r in rows:
            v = r[col_i]
            if v is not None:
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    pass

        if not values:
            return None

        if fn == "sum":
            return round(sum(values), 4)
        if fn == "avg":
            return round(sum(values) / len(values), 4)
        if fn == "min":
            return min(values)
        if fn == "max":
            return max(values)
        if fn == "median":
            s = sorted(values)
            n = len(s)
            mid = n // 2
            if n % 2 == 0:
                return round((s[mid - 1] + s[mid]) / 2, 4)
            return s[mid]
        return None

    # ------------------------------------------------------------------
    # filter_data  (NC-9)
    # ------------------------------------------------------------------

    def _filter_data(
        self,
        qr: QueryResult,
        params: dict[str, Any],
    ) -> ProcessedData:
        column: str = params.get("column", "")
        op: str = params.get("op", "eq")
        value: Any = params.get("value")
        exclude_empty: bool = params.get("exclude_empty", False)

        if not column:
            raise ValueError("filter_data requires a 'column' parameter")
        if column not in qr.columns:
            raise ValueError(f"Column '{column}' not found. Available: {', '.join(qr.columns)}")

        col_idx = qr.columns.index(column)
        filtered: list[list[Any]] = []

        for row in qr.rows:
            cell = row[col_idx]
            if exclude_empty and (cell is None or str(cell).strip() == ""):
                continue
            if value is not None:
                if not self._filter_match(cell, op, value):
                    continue
            filtered.append(row)

        result_qr = QueryResult(
            columns=list(qr.columns),
            rows=filtered,
            row_count=len(filtered),
            execution_time_ms=qr.execution_time_ms,
        )

        summary = (
            f"Filtered {len(qr.rows)} rows to {len(filtered)} rows on column '{column}' (op={op})."
        )
        return ProcessedData(query_result=result_qr, summary=summary)

    @staticmethod
    def _filter_match(cell: Any, op: str, value: Any) -> bool:
        cell_str = str(cell) if cell is not None else ""
        val_str = str(value)
        if op == "eq":
            return cell_str == val_str
        if op == "neq":
            return cell_str != val_str
        if op == "contains":
            return val_str.lower() in cell_str.lower()
        if op == "not_contains":
            return val_str.lower() not in cell_str.lower()
        if op in ("gt", "gte", "lt", "lte"):
            try:
                cv, vv = float(cell), float(value)
            except (ValueError, TypeError):
                return False
            if op == "gt":
                return cv > vv
            if op == "gte":
                return cv >= vv
            if op == "lt":
                return cv < vv
            return cv <= vv
        if op == "in":
            allowed = [v.strip() for v in val_str.split(",")]
            return cell_str in allowed
        return True


_processor_instance: DataProcessor | None = None


def get_data_processor() -> DataProcessor:
    """Return the module-level DataProcessor singleton."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = DataProcessor()
    return _processor_instance
