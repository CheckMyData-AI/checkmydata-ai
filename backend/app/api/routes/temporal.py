"""API routes for Temporal Intelligence."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.temporal_intelligence import TemporalIntelligenceService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["temporal"])

_membership_svc = MembershipService()
_svc = TemporalIntelligenceService()


class AnalyzeSeriesRequest(BaseModel):
    """Analyze a single time series."""

    project_id: str
    values: list[float] = Field(..., min_length=1, max_length=10000)
    metric_name: str = "metric"
    period_label: str = "day"


class DetectLagRequest(BaseModel):
    """Detect lag between two series."""

    project_id: str
    series_a: list[float] = Field(..., min_length=3, max_length=10000)
    series_b: list[float] = Field(..., min_length=3, max_length=10000)
    max_lag: int = Field(14, ge=1, le=100)


@router.post("/{project_id}/analyze")
async def analyze_series(
    project_id: str,
    req: AnalyzeSeriesRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Analyze a time series for trends, seasonality, and anomalies."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    report = _svc.analyze_series(req.values, req.metric_name, req.period_label)
    return report.to_dict()


@router.post("/{project_id}/lag")
async def detect_lag(
    project_id: str,
    req: DetectLagRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Detect lag/lead relationship between two time series."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    result = _svc.detect_lag(req.series_a, req.series_b, req.max_lag)
    return result.to_dict()
