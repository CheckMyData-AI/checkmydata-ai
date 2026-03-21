import json
import logging

logger = logging.getLogger(__name__)

_OPERATORS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "eq": lambda a, b: a == b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
}


class AlertEvaluator:
    @staticmethod
    def evaluate(
        result_rows: list[list],
        columns: list[str],
        conditions_json: str | None,
    ) -> list[dict]:
        if not conditions_json:
            return []

        try:
            conditions = json.loads(conditions_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid alert_conditions JSON: %s", (conditions_json or "")[:200])
            return []

        if not isinstance(conditions, list) or not result_rows:
            return []

        col_index = {c: i for i, c in enumerate(columns)}
        triggered: list[dict] = []

        for cond in conditions:
            col_name = cond.get("column", "")
            operator = cond.get("operator", "")
            threshold = cond.get("threshold")

            if col_name not in col_index:
                continue
            if threshold is None:
                continue

            idx = col_index[col_name]
            threshold = float(threshold)

            if operator == "pct_change":
                if len(result_rows) < 2:
                    continue
                try:
                    prev_val = float(result_rows[-2][idx])
                    curr_val = float(result_rows[-1][idx])
                except (ValueError, TypeError, IndexError):
                    continue
                if prev_val == 0:
                    continue
                pct = ((curr_val - prev_val) / abs(prev_val)) * 100
                if abs(pct) >= threshold:
                    triggered.append(
                        {
                            "condition": cond,
                            "actual_value": round(pct, 2),
                            "threshold": threshold,
                            "message": (
                                f"{col_name} changed by {pct:+.1f}% (threshold: {threshold}%)"
                            ),
                        }
                    )
                continue

            op_fn = _OPERATORS.get(operator)
            if not op_fn:
                continue

            for row in result_rows:
                try:
                    val = float(row[idx])
                except (ValueError, TypeError, IndexError):
                    continue
                if op_fn(val, threshold):
                    triggered.append(
                        {
                            "condition": cond,
                            "actual_value": val,
                            "threshold": threshold,
                            "message": (f"{col_name} = {val} {operator} {threshold}"),
                        }
                    )
                    break

        return triggered
