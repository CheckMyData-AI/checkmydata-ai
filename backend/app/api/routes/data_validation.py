"""Data validation API endpoints.

Investigation-related endpoints live in :mod:`data_investigations` (T24).
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.models.data_validation import DataInvestigation
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_membership_svc = MembershipService()
_conn_svc = ConnectionService()


# ------------------------------------------------------------------
# Validation endpoints
# ------------------------------------------------------------------


class ValidateDataRequest(BaseModel):
    connection_id: str
    session_id: str
    message_id: str
    query: str
    verdict: Literal["confirmed", "rejected", "approximate", "unknown"]
    metric_description: str = ""
    agent_value: str = ""
    user_expected_value: str | None = None
    deviation_pct: float | None = None
    rejection_reason: str | None = None
    project_id: str


@router.post("/validate-data")
@limiter.limit("20/minute")
async def validate_data(
    request: Request,
    body: ValidateDataRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    from app.services.data_validation_service import DataValidationService
    from app.services.feedback_pipeline import FeedbackPipeline

    val_svc = DataValidationService()
    pipeline = FeedbackPipeline()

    async with db.begin_nested():
        feedback = await val_svc.record_validation(
            db,
            connection_id=body.connection_id,
            session_id=body.session_id,
            message_id=body.message_id,
            query=body.query,
            verdict=body.verdict,
            metric_description=body.metric_description,
            agent_value=body.agent_value,
            user_expected_value=body.user_expected_value,
            deviation_pct=body.deviation_pct,
            rejection_reason=body.rejection_reason,
        )

        result = await pipeline.process(db, feedback, body.project_id)
    await db.commit()

    audit_log(
        "data_validation.validate",
        user_id=user["user_id"],
        project_id=body.project_id,
        detail=f"verdict={body.verdict}",
    )
    return {
        "ok": True,
        "feedback_id": feedback.id,
        "verdict": body.verdict,
        "learnings_created": result.get("learnings_created", []),
        "notes_created": result.get("notes_created", []),
        "benchmark_updated": result.get("benchmark_updated", False),
        "resolution": result.get("resolution", ""),
    }


@router.get("/validation-stats/{connection_id}")
async def get_validation_stats(
    connection_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from app.services.data_validation_service import DataValidationService

    svc = DataValidationService()
    stats = await svc.get_accuracy_stats(db, connection_id)
    return stats


@router.get("/benchmarks/{connection_id}")
async def get_benchmarks(
    connection_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from app.services.benchmark_service import BenchmarkService

    svc = BenchmarkService()
    benchmarks = await svc.get_all_for_connection(db, connection_id)

    return [
        {
            "id": b.id,
            "metric_key": b.metric_key,
            "metric_description": b.metric_description,
            "value": b.value,
            "value_numeric": b.value_numeric,
            "unit": b.unit,
            "confidence": b.confidence,
            "source": b.source,
            "times_confirmed": b.times_confirmed,
            "last_confirmed_at": b.last_confirmed_at.isoformat() if b.last_confirmed_at else None,
        }
        for b in benchmarks
    ]


@router.get("/analytics/{project_id}")
async def get_feedback_analytics(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Aggregate feedback analytics across all connections in a project."""
    await _membership_svc.require_role(
        db,
        project_id,
        user["user_id"],
        "owner",
    )

    from sqlalchemy import func as sa_func

    from app.models.agent_learning import AgentLearning
    from app.models.benchmark import DataBenchmark
    from app.models.connection import Connection
    from app.models.data_validation import (
        DataValidationFeedback,
    )

    conn_result = await db.execute(select(Connection.id).where(Connection.project_id == project_id))
    conn_ids = [r[0] for r in conn_result.all()]
    if not conn_ids:
        return {
            "connections": 0,
            "validations": {},
            "learnings": {},
            "benchmarks": {},
            "investigations": {},
        }

    val_result = await db.execute(
        select(
            DataValidationFeedback.verdict,
            sa_func.count(DataValidationFeedback.id),
        )
        .where(DataValidationFeedback.connection_id.in_(conn_ids))
        .group_by(DataValidationFeedback.verdict)
    )
    verdict_counts = {str(r[0]): int(r[1]) for r in val_result.all()}
    total_validations = sum(verdict_counts.values())
    confirmed = verdict_counts.get("confirmed", 0)
    accuracy_rate = round(confirmed / total_validations * 100, 1) if total_validations > 0 else None

    top_rejections = await db.execute(
        select(
            DataValidationFeedback.rejection_reason,
            sa_func.count(DataValidationFeedback.id),
        )
        .where(
            DataValidationFeedback.connection_id.in_(conn_ids),
            DataValidationFeedback.verdict == "rejected",
            DataValidationFeedback.rejection_reason.isnot(None),
        )
        .group_by(DataValidationFeedback.rejection_reason)
        .order_by(sa_func.count(DataValidationFeedback.id).desc())
        .limit(10)
    )
    error_patterns = [{"reason": str(r[0]), "count": int(r[1])} for r in top_rejections.all()]

    learning_result = await db.execute(
        select(
            AgentLearning.category,
            sa_func.count(AgentLearning.id),
        )
        .where(
            AgentLearning.connection_id.in_(conn_ids),
            AgentLearning.is_active.is_(True),
        )
        .group_by(AgentLearning.category)
    )
    learning_by_cat = {str(r[0]): int(r[1]) for r in learning_result.all()}
    total_learnings = sum(learning_by_cat.values())

    bm_count = await db.execute(
        select(sa_func.count(DataBenchmark.id)).where(
            DataBenchmark.connection_id.in_(conn_ids),
            DataBenchmark.confidence >= 0.3,
        )
    )
    total_benchmarks = bm_count.scalar_one()

    inv_result = await db.execute(
        select(
            DataInvestigation.status,
            sa_func.count(DataInvestigation.id),
        )
        .where(DataInvestigation.connection_id.in_(conn_ids))
        .group_by(DataInvestigation.status)
    )
    inv_by_status = {str(r[0]): int(r[1]) for r in inv_result.all()}

    return {
        "connections": len(conn_ids),
        "validations": {
            "total": total_validations,
            "by_verdict": verdict_counts,
            "accuracy_rate": accuracy_rate,
            "top_error_patterns": error_patterns,
        },
        "learnings": {
            "total_active": total_learnings,
            "by_category": learning_by_cat,
        },
        "benchmarks": {
            "total": total_benchmarks,
        },
        "investigations": inv_by_status,
    }


@router.get("/summary/{project_id}")
async def get_analytics_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Lightweight summary: accuracy_rate, total_validations, active_learnings, benchmark_count."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

    from sqlalchemy import func as sa_func

    from app.models.agent_learning import AgentLearning
    from app.models.benchmark import DataBenchmark
    from app.models.connection import Connection
    from app.models.data_validation import DataValidationFeedback

    conn_result = await db.execute(select(Connection.id).where(Connection.project_id == project_id))
    conn_ids = [r[0] for r in conn_result.all()]
    if not conn_ids:
        return {
            "accuracy_rate": None,
            "total_validations": 0,
            "active_learnings": 0,
            "benchmark_count": 0,
        }

    val_result = await db.execute(
        select(
            DataValidationFeedback.verdict,
            sa_func.count(DataValidationFeedback.id),
        )
        .where(DataValidationFeedback.connection_id.in_(conn_ids))
        .group_by(DataValidationFeedback.verdict)
    )
    verdict_counts = {str(r[0]): int(r[1]) for r in val_result.all()}
    total_validations = sum(verdict_counts.values())
    confirmed = verdict_counts.get("confirmed", 0)
    accuracy_rate = round(confirmed / total_validations * 100, 1) if total_validations > 0 else None

    learning_count = await db.execute(
        select(sa_func.count(AgentLearning.id)).where(
            AgentLearning.connection_id.in_(conn_ids),
            AgentLearning.is_active.is_(True),
        )
    )

    bm_count = await db.execute(
        select(sa_func.count(DataBenchmark.id)).where(
            DataBenchmark.connection_id.in_(conn_ids),
            DataBenchmark.confidence >= 0.3,
        )
    )

    return {
        "accuracy_rate": accuracy_rate,
        "total_validations": total_validations,
        "active_learnings": learning_count.scalar_one(),
        "benchmark_count": bm_count.scalar_one(),
    }


# ------------------------------------------------------------------
# Anomaly Intelligence endpoints
# ------------------------------------------------------------------


class AnomalyAnalysisRequest(BaseModel):
    project_id: str = Field(..., max_length=64)
    connection_id: str = Field(..., max_length=64)
    query: str = Field("", max_length=10000)
    question: str = Field("", max_length=2000)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    columns: list[str] = Field(default_factory=list, max_length=500)


@router.post("/anomaly-analysis")
@limiter.limit("30/minute")
async def run_anomaly_analysis(
    request: Request,
    body: AnomalyAnalysisRequest,
    user: dict = Depends(get_current_user),
):
    """Run Anomaly Intelligence Engine on provided data."""
    from app.core.anomaly_intelligence import AnomalyIntelligenceEngine

    engine = AnomalyIntelligenceEngine()
    reports = engine.analyze(
        rows=body.rows,
        columns=body.columns,
        query=body.query,
        question=body.question,
    )

    return {
        "ok": True,
        "total": len(reports),
        "reports": [r.to_dict() for r in reports],
        "summary": engine.format_report(reports),
    }


@router.post("/anomaly-scan/{connection_id}")
@limiter.limit("5/minute")
async def scan_connection_anomalies(
    request: Request,
    connection_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Scan a connection's tables for anomalies using probes."""
    await _membership_svc.require_role(
        db,
        project_id,
        user["user_id"],
        "viewer",
    )

    from app.models.connection import Connection
    from app.models.db_index import DbIndex
    from app.services.connection_service import ConnectionService

    conn_svc = ConnectionService()
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.project_id == project_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connection not found")

    cfg = await conn_svc.to_config(db, conn)

    idx_result = await db.execute(
        select(DbIndex.table_name)
        .where(
            DbIndex.connection_id == connection_id,
        )
        .limit(10)
    )
    tables = [r[0] for r in idx_result.all()]
    if not tables:
        return {"ok": True, "tables_scanned": 0, "results": []}

    from app.services.probe_service import ProbeService

    probe_svc = ProbeService()
    report = await probe_svc.run_probes(
        session=db,
        connection_id=connection_id,
        project_id=project_id,
        cfg=cfg,
        table_names=tables,
    )
    await db.commit()

    return {
        "ok": True,
        "tables_scanned": len(report),
        "results": report,
    }
