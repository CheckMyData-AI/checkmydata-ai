"""Insights API — memory layer access, insight lifecycle management."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.insight_memory import InsightMemoryService
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_insight_svc = InsightMemoryService()
_membership_svc = MembershipService()


class InsightResponse(BaseModel):
    id: str
    insight_type: str
    severity: str
    title: str
    description: str
    recommended_action: str
    expected_impact: str
    confidence: float
    status: str
    user_verdict: str | None
    times_surfaced: int
    times_confirmed: int
    connection_id: str | None
    detected_at: str


class InsightSummaryResponse(BaseModel):
    total_active: int
    by_type: dict[str, int]
    by_severity: dict[str, int]


class InsightFeedbackRequest(BaseModel):
    feedback: str = ""


class CreateInsightRequest(BaseModel):
    connection_id: str | None = None
    insight_type: Literal[
        "anomaly", "opportunity", "loss", "trend", "pattern",
        "reconciliation_mismatch", "data_quality", "observation",
    ]
    severity: Literal["critical", "warning", "info", "positive"] = "info"
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1)
    recommended_action: str = ""
    expected_impact: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)


@router.get("/{project_id}")
async def list_insights(
    project_id: str,
    connection_id: str | None = None,
    insight_type: str | None = None,
    severity: str | None = None,
    status: str = "active",
    min_confidence: float = 0.0,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    insights = await _insight_svc.get_insights(
        db,
        project_id,
        connection_id=connection_id,
        insight_type=insight_type,
        severity=severity,
        status=status,
        min_confidence=min_confidence,
        limit=min(limit, 100),
        offset=offset,
    )
    return [
        InsightResponse(
            id=i.id,
            insight_type=i.insight_type,
            severity=i.severity,
            title=i.title,
            description=i.description,
            recommended_action=i.recommended_action,
            expected_impact=i.expected_impact,
            confidence=round(i.confidence, 2),
            status=i.status,
            user_verdict=i.user_verdict,
            times_surfaced=i.times_surfaced,
            times_confirmed=i.times_confirmed,
            connection_id=i.connection_id,
            detected_at=i.detected_at.isoformat() if i.detected_at else "",
        )
        for i in insights
    ]


@router.get("/{project_id}/summary")
async def get_insight_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _insight_svc.get_summary(db, project_id)


@router.post("/{project_id}")
@limiter.limit("30/minute")
async def create_insight(
    request: Request,
    project_id: str,
    body: CreateInsightRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    record = await _insight_svc.store_insight(
        db,
        project_id,
        body.insight_type,
        body.title,
        body.description,
        connection_id=body.connection_id,
        severity=body.severity,
        recommended_action=body.recommended_action,
        expected_impact=body.expected_impact,
        confidence=body.confidence,
    )
    await db.commit()
    return {"id": record.id}


@router.patch("/{project_id}/{insight_id}/confirm")
@limiter.limit("30/minute")
async def confirm_insight(
    request: Request,
    project_id: str,
    insight_id: str,
    body: InsightFeedbackRequest = InsightFeedbackRequest(),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    insight_id = validate_safe_id(insight_id, "insight_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    record = await _insight_svc.confirm_insight(db, insight_id, body.feedback)
    if not record:
        raise HTTPException(status_code=404, detail="Insight not found")
    await db.commit()
    return {"status": record.status, "confidence": round(record.confidence, 2)}


@router.patch("/{project_id}/{insight_id}/dismiss")
@limiter.limit("30/minute")
async def dismiss_insight(
    request: Request,
    project_id: str,
    insight_id: str,
    body: InsightFeedbackRequest = InsightFeedbackRequest(),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    insight_id = validate_safe_id(insight_id, "insight_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    record = await _insight_svc.dismiss_insight(db, insight_id, body.feedback)
    if not record:
        raise HTTPException(status_code=404, detail="Insight not found")
    await db.commit()
    return {"status": record.status, "confidence": round(record.confidence, 2)}


@router.patch("/{project_id}/{insight_id}/resolve")
@limiter.limit("30/minute")
async def resolve_insight(
    request: Request,
    project_id: str,
    insight_id: str,
    body: InsightFeedbackRequest = InsightFeedbackRequest(),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    insight_id = validate_safe_id(insight_id, "insight_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    record = await _insight_svc.resolve_insight(db, insight_id, body.feedback)
    if not record:
        raise HTTPException(status_code=404, detail="Insight not found")
    await db.commit()
    return {"status": record.status}
