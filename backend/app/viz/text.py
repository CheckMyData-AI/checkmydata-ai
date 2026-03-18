from app.connectors.base import QueryResult
from app.viz.utils import serialize_value


def format_text(result: QueryResult, summary: str = "") -> dict:
    if result.row_count == 0:
        return {
            "type": "text",
            "content": summary or "No results found.",
        }

    if result.row_count == 1 and len(result.columns) == 1 and result.rows:
        return {
            "type": "number",
            "value": serialize_value(result.rows[0][0]),
            "label": result.columns[0],
            "summary": summary,
        }

    if result.row_count == 1 and result.rows:
        kv_pairs = {col: serialize_value(result.rows[0][i]) for i, col in enumerate(result.columns)}
        return {
            "type": "key_value",
            "data": kv_pairs,
            "summary": summary,
        }

    return {
        "type": "text",
        "content": summary,
        "row_count": result.row_count,
    }
