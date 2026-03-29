import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.alert_evaluator import AlertEvaluator
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = SchedulerService()
_conn_svc = ConnectionService()
_membership_svc = MembershipService()


class ScheduleCreate(BaseModel):
    project_id: str
    connection_id: str
    title: str = Field(max_length=200)
    sql_query: str = Field(max_length=50000)
    cron_expression: str = Field(max_length=100)
    alert_conditions: str | None = Field(None, max_length=10000)
    notification_channels: str | None = Field(None, max_length=5000)

    @field_validator("alert_conditions", mode="before")
    @classmethod
    def validate_alert_json(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, list):
                    raise ValueError("alert_conditions must be a JSON array")
            except json.JSONDecodeError:
                raise ValueError("alert_conditions must be valid JSON")
        return v


class ScheduleUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    sql_query: str | None = Field(None, max_length=50000)
    cron_expression: str | None = Field(None, max_length=100)
    alert_conditions: str | None = Field(None, max_length=10000)
    notification_channels: str | None = Field(None, max_length=5000)
    is_active: bool | None = None

    @field_validator("alert_conditions", mode="before")
    @classmethod
    def validate_alert_json(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, list):
                    raise ValueError("alert_conditions must be a JSON array")
            except json.JSONDecodeError:
                raise ValueError("alert_conditions must be valid JSON")
        return v


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    project_id: str
    connection_id: str
    title: str
    sql_query: str
    cron_expression: str
    alert_conditions: str | None
    notification_channels: str | None
    is_active: bool
    last_run_at: datetime | None
    last_result_json: str | None
    next_run_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: str
    status: str
    result_summary: str | None
    alerts_fired: str | None
    executed_at: datetime | None
    duration_ms: int | None


@router.post("", response_model=ScheduleResponse)
@limiter.limit("10/minute")
async def create_schedule(
    request: Request,
    body: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "owner")

    if not SchedulerService.validate_cron(body.cron_expression):
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    conn = await _conn_svc.get(db, body.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.project_id != body.project_id:
        raise HTTPException(status_code=400, detail="Connection does not belong to this project")

    schedule = await _svc.create_schedule(
        db,
        user_id=user["user_id"],
        project_id=body.project_id,
        connection_id=body.connection_id,
        title=body.title,
        sql_query=body.sql_query,
        cron_expression=body.cron_expression,
        alert_conditions=body.alert_conditions,
        notification_channels=body.notification_channels,
    )
    audit_log(
        "schedule.create",
        user_id=user["user_id"],
        project_id=body.project_id,
        resource_type="schedule",
        resource_id=schedule.id,
    )
    return schedule


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_schedules(db, project_id, skip=skip, limit=limit)


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    schedule = await _svc.get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _membership_svc.require_role(db, schedule.project_id, user["user_id"], "viewer")
    return schedule


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    schedule = await _svc.get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _membership_svc.require_role(db, schedule.project_id, user["user_id"], "owner")

    updates = body.model_dump(exclude_unset=True)
    cron = updates.get("cron_expression")
    if cron and not SchedulerService.validate_cron(cron):
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    updated = await _svc.update_schedule(db, schedule_id, **updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Schedule not found after update")

    audit_log(
        "schedule.update",
        user_id=user["user_id"],
        project_id=schedule.project_id,
        resource_type="schedule",
        resource_id=schedule_id,
    )
    return updated


@router.delete("/{schedule_id}")
@limiter.limit("10/minute")
async def delete_schedule(
    request: Request,
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    schedule = await _svc.get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _membership_svc.require_role(db, schedule.project_id, user["user_id"], "owner")

    await _svc.delete_schedule(db, schedule_id)
    audit_log(
        "schedule.delete",
        user_id=user["user_id"],
        project_id=schedule.project_id,
        resource_type="schedule",
        resource_id=schedule_id,
    )
    return {"ok": True}


@router.post("/{schedule_id}/run-now", response_model=RunResponse)
@limiter.limit("5/minute")
async def run_now(
    request: Request,
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    schedule = await _svc.get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _membership_svc.require_role(db, schedule.project_id, user["user_id"], "owner")

    conn_model = await _conn_svc.get(db, schedule.connection_id)
    if not conn_model:
        raise HTTPException(status_code=404, detail="Connection not found")

    config = await _conn_svc.to_config(db, conn_model, user_id=user["user_id"])

    from app.connectors.registry import get_connector
    from app.core.safety import SafetyGuard
    from app.viz.utils import serialize_value

    guard = SafetyGuard()
    safety = guard.validate(schedule.sql_query, conn_model.db_type)
    if not safety.is_safe:
        raise HTTPException(status_code=400, detail=f"Query blocked: {safety.reason}")

    connector = get_connector(conn_model.db_type, ssh_exec_mode=config.ssh_exec_mode)
    start = time.monotonic()
    try:
        await connector.connect(config)
        try:
            result = await connector.execute_query(schedule.sql_query)
        finally:
            await connector.disconnect()
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        run = await _svc.record_run(
            db,
            schedule_id,
            status="failed",
            result_summary=json.dumps({"error": str(e)}),
            duration_ms=duration_ms,
        )
        return run

    duration_ms = int((time.monotonic() - start) * 1000)
    cols = list(getattr(result, "columns", []))
    rows = getattr(result, "rows", []) or []
    serialized_rows = [[serialize_value(v) for v in row] for row in rows[:500]]

    max_result_bytes = 1_000_000
    result_summary = json.dumps(
        {
            "columns": cols,
            "rows": serialized_rows,
            "total_rows": getattr(result, "row_count", len(rows)),
        },
        default=str,
    )
    if len(result_summary) > max_result_bytes:
        serialized_rows = serialized_rows[:50]
        result_summary = json.dumps(
            {
                "columns": cols,
                "rows": serialized_rows,
                "total_rows": getattr(result, "row_count", len(rows)),
                "truncated": True,
            },
            default=str,
        )

    alerts = AlertEvaluator.evaluate(serialized_rows, cols, schedule.alert_conditions)
    status = "alert_triggered" if alerts else "success"
    alerts_json = json.dumps(alerts) if alerts else None

    if alerts:
        from app.models.notification import Notification

        for alert in alerts:
            notif = Notification(
                user_id=schedule.user_id,
                project_id=schedule.project_id,
                title=f"Alert: {schedule.title}",
                body=alert.get("message", ""),
                type="alert",
            )
            db.add(notif)

    run = await _svc.record_run(
        db,
        schedule_id,
        status=status,
        result_summary=result_summary,
        alerts_fired=alerts_json,
        duration_ms=duration_ms,
    )

    audit_log(
        "schedule.run_now",
        user_id=user["user_id"],
        project_id=schedule.project_id,
        resource_type="schedule",
        resource_id=schedule_id,
    )
    return run


@router.get("/{schedule_id}/history", response_model=list[RunResponse])
async def get_history(
    schedule_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    schedule = await _svc.get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _membership_svc.require_role(db, schedule.project_id, user["user_id"], "viewer")
    return await _svc.get_run_history(db, schedule_id, skip=skip, limit=limit)
