import csv
import io
import json

from openpyxl import Workbook

from app.connectors.base import QueryResult
from app.viz.utils import serialize_value


def export_csv(result: QueryResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(result.columns)
    for row in result.rows:
        writer.writerow([serialize_value(v) for v in row])
    return output.getvalue()


def export_json(result: QueryResult) -> str:
    data = []
    for row in result.rows:
        data.append({col: serialize_value(v) for col, v in zip(result.columns, row)})
    return json.dumps(data, indent=2, default=str)


def export_xlsx(result: QueryResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Query Results"

    ws.append(result.columns)
    for row in result.rows:
        ws.append([serialize_value(v) for v in row])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
