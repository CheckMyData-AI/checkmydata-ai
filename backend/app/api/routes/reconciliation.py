"""API routes for Cross-Source Reconciliation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.reconciliation_engine import ReconciliationEngine
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reconciliation"])

_membership_svc = MembershipService()


class ReconcileRowCountsRequest(BaseModel):
    """Compare row counts between two connections."""

    project_id: str
    source_a_connection_id: str
    source_a_name: str = "Source A"
    source_b_connection_id: str
    source_b_name: str = "Source B"
    counts_a: dict[str, int] = Field(
        ...,
        description="Table name → row count for source A",
    )
    counts_b: dict[str, int] = Field(
        ...,
        description="Table name → row count for source B",
    )


class ReconcileValuesRequest(BaseModel):
    """Compare aggregate metric values between two connections."""

    project_id: str
    source_a_connection_id: str
    source_a_name: str = "Source A"
    source_b_connection_id: str
    source_b_name: str = "Source B"
    aggregates_a: dict[str, float] = Field(
        ...,
        description="Metric name → aggregate value for source A",
    )
    aggregates_b: dict[str, float] = Field(
        ...,
        description="Metric name → aggregate value for source B",
    )


class ReconcileSchemasRequest(BaseModel):
    """Compare table schemas between two connections."""

    project_id: str
    source_a_connection_id: str
    source_a_name: str = "Source A"
    source_b_connection_id: str
    source_b_name: str = "Source B"
    schema_a: dict[str, list[str]] = Field(
        ...,
        description="Table name → column list for source A",
    )
    schema_b: dict[str, list[str]] = Field(
        ...,
        description="Table name → column list for source B",
    )


class ReconcileFullRequest(BaseModel):
    """Run a full reconciliation suite between two connections."""

    project_id: str
    source_a_connection_id: str
    source_a_name: str = "Source A"
    source_b_connection_id: str
    source_b_name: str = "Source B"
    counts_a: dict[str, int] = Field(default_factory=dict)
    counts_b: dict[str, int] = Field(default_factory=dict)
    aggregates_a: dict[str, float] = Field(default_factory=dict)
    aggregates_b: dict[str, float] = Field(default_factory=dict)
    schema_a: dict[str, list[str]] = Field(default_factory=dict)
    schema_b: dict[str, list[str]] = Field(default_factory=dict)


_engine = ReconciliationEngine()


async def _validate_connection_ownership(
    db: AsyncSession,
    project_id: str,
    connection_id: str,
    label: str,
) -> None:
    """Verify a connection belongs to the given project."""
    from sqlalchemy import select

    from app.models.connection import Connection

    result = await db.execute(
        select(Connection.id).where(
            Connection.id == connection_id,
            Connection.project_id == project_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"{label} connection does not belong to this project",
        )


@router.post("/{project_id}/row-counts")
async def reconcile_row_counts(
    project_id: str,
    req: ReconcileRowCountsRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Compare row counts between two data sources."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    await _validate_connection_ownership(db, project_id, req.source_a_connection_id, "Source A")
    await _validate_connection_ownership(db, project_id, req.source_b_connection_id, "Source B")

    discrepancies = _engine.reconcile_row_counts(
        req.source_a_name,
        req.source_b_name,
        req.counts_a,
        req.counts_b,
    )
    report = _engine.build_report(
        req.source_a_name,
        req.source_b_name,
        req.source_a_connection_id,
        req.source_b_connection_id,
        discrepancies,
        total_checks=len(set(req.counts_a.keys()) | set(req.counts_b.keys())),
    )
    return report.to_dict()


@router.post("/{project_id}/values")
async def reconcile_values(
    project_id: str,
    req: ReconcileValuesRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Compare aggregate metric values between two data sources."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    await _validate_connection_ownership(db, project_id, req.source_a_connection_id, "Source A")
    await _validate_connection_ownership(db, project_id, req.source_b_connection_id, "Source B")

    discrepancies = _engine.reconcile_aggregate_values(
        req.source_a_name,
        req.source_b_name,
        req.aggregates_a,
        req.aggregates_b,
    )
    report = _engine.build_report(
        req.source_a_name,
        req.source_b_name,
        req.source_a_connection_id,
        req.source_b_connection_id,
        discrepancies,
        total_checks=len(set(req.aggregates_a.keys()) | set(req.aggregates_b.keys())),
    )
    return report.to_dict()


@router.post("/{project_id}/schemas")
async def reconcile_schemas(
    project_id: str,
    req: ReconcileSchemasRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Compare table schemas (column lists) between two data sources."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    await _validate_connection_ownership(db, project_id, req.source_a_connection_id, "Source A")
    await _validate_connection_ownership(db, project_id, req.source_b_connection_id, "Source B")

    discrepancies = _engine.reconcile_schemas(
        req.source_a_name,
        req.source_b_name,
        req.schema_a,
        req.schema_b,
    )
    report = _engine.build_report(
        req.source_a_name,
        req.source_b_name,
        req.source_a_connection_id,
        req.source_b_connection_id,
        discrepancies,
        total_checks=len(set(req.schema_a.keys()) | set(req.schema_b.keys())),
    )
    return report.to_dict()


@router.post("/{project_id}/full")
async def reconcile_full(
    project_id: str,
    req: ReconcileFullRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Run a full reconciliation between two data sources.

    Combines row counts, aggregate values, and schema comparison.
    """
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    await _validate_connection_ownership(db, project_id, req.source_a_connection_id, "Source A")
    await _validate_connection_ownership(db, project_id, req.source_b_connection_id, "Source B")

    all_discrepancies: list = []
    total_checks = 0

    if req.counts_a or req.counts_b:
        disc = _engine.reconcile_row_counts(
            req.source_a_name,
            req.source_b_name,
            req.counts_a,
            req.counts_b,
        )
        all_discrepancies.extend(disc)
        total_checks += len(set(req.counts_a.keys()) | set(req.counts_b.keys()))

    if req.aggregates_a or req.aggregates_b:
        disc = _engine.reconcile_aggregate_values(
            req.source_a_name,
            req.source_b_name,
            req.aggregates_a,
            req.aggregates_b,
        )
        all_discrepancies.extend(disc)
        total_checks += len(set(req.aggregates_a.keys()) | set(req.aggregates_b.keys()))

    if req.schema_a or req.schema_b:
        disc = _engine.reconcile_schemas(
            req.source_a_name,
            req.source_b_name,
            req.schema_a,
            req.schema_b,
        )
        all_discrepancies.extend(disc)
        total_checks += len(set(req.schema_a.keys()) | set(req.schema_b.keys()))

    from app.core.insight_memory import InsightMemoryService

    insight_svc = InsightMemoryService()
    for disc in all_discrepancies:
        if disc.severity in ("critical", "warning"):
            try:
                await insight_svc.store_insight(
                    db,
                    project_id=project_id,
                    connection_id=req.source_a_connection_id,
                    insight_type="reconciliation",
                    severity=disc.severity,
                    title=disc.title,
                    description=disc.description,
                    confidence=0.85 if disc.severity == "critical" else 0.7,
                    recommended_action=disc.recommended_action,
                    expected_impact=(
                        f"{disc.difference_pct}% discrepancy" if disc.difference_pct else ""
                    ),
                )
            except Exception:
                logger.warning("Failed to store reconciliation insight", exc_info=True)

    report = _engine.build_report(
        req.source_a_name,
        req.source_b_name,
        req.source_a_connection_id,
        req.source_b_connection_id,
        all_discrepancies,
        total_checks,
    )
    return report.to_dict()
