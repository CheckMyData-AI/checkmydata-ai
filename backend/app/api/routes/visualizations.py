from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.connectors.base import QueryResult
from app.core.rate_limit import limiter
from app.viz.export import export_csv, export_json, export_xlsx
from app.viz.renderer import render

router = APIRouter()


class RenderRequest(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    viz_type: str = Field(default="table", max_length=50)
    config: dict = {}
    summary: str = ""


class ExportRequest(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    format: str = Field(default="csv", max_length=50)


@router.post("/render")
@limiter.limit("20/minute")
async def render_visualization(
    request: Request, body: RenderRequest, user: dict = Depends(get_current_user)
):
    result = QueryResult(
        columns=body.columns,
        rows=body.rows,
        row_count=len(body.rows),
    )
    return render(result, body.viz_type, body.config, body.summary)


@router.post("/export")
@limiter.limit("20/minute")
async def export_data(
    request: Request,
    body: ExportRequest,
    user: dict = Depends(get_current_user),
):
    result = QueryResult(
        columns=body.columns,
        rows=body.rows,
        row_count=len(body.rows),
    )

    if body.format == "csv":
        content = export_csv(result)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=export.csv"},
        )
    elif body.format == "json":
        content = export_json(result)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=export.json"},
        )
    elif body.format == "xlsx":
        xlsx_content = export_xlsx(result)
        return Response(
            content=xlsx_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=export.xlsx"},
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {body.format}")
