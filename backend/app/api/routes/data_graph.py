"""Data Graph API — metrics registry and relationship management."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.data_graph import DataGraphService
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_graph_svc = DataGraphService()
_membership_svc = MembershipService()


class MetricResponse(BaseModel):
    id: str
    name: str
    display_name: str
    description: str
    category: str
    source_table: str | None
    source_column: str | None
    aggregation: str
    unit: str
    confidence: float
    times_referenced: int
    connection_id: str | None


class RelationshipResponse(BaseModel):
    id: str
    metric_a_id: str
    metric_b_id: str
    relationship_type: str
    strength: float
    direction: str
    description: str
    confidence: float


class GraphSummaryResponse(BaseModel):
    total_metrics: int
    total_relationships: int
    categories: dict[str, int]


class UpsertMetricRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    connection_id: str | None = None
    display_name: str = ""
    description: str = ""
    category: str = "general"
    source_table: str | None = None
    source_column: str | None = None
    aggregation: str = ""
    formula: str = ""
    unit: str = ""
    data_type: str = "numeric"


class AddRelationshipRequest(BaseModel):
    metric_a_id: str
    metric_b_id: str
    relationship_type: Literal[
        "correlation", "dependency", "causation_hypothesis",
        "foreign_key", "derived_from", "same_entity",
    ]
    strength: float = Field(0.0, ge=0.0, le=1.0)
    direction: Literal["bidirectional", "a_to_b", "b_to_a"] = "bidirectional"
    description: str = ""
    evidence: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)


@router.get("/{project_id}/summary")
async def get_graph_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _graph_svc.get_graph_summary(db, project_id)


@router.get("/{project_id}/metrics")
async def list_metrics(
    project_id: str,
    connection_id: str | None = None,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    metrics = await _graph_svc.get_metrics(
        db, project_id, connection_id=connection_id, category=category
    )
    return [
        MetricResponse(
            id=m.id,
            name=m.name,
            display_name=m.display_name,
            description=m.description,
            category=m.category,
            source_table=m.source_table,
            source_column=m.source_column,
            aggregation=m.aggregation,
            unit=m.unit,
            confidence=m.confidence,
            times_referenced=m.times_referenced,
            connection_id=m.connection_id,
        )
        for m in metrics
    ]


@router.post("/{project_id}/metrics")
@limiter.limit("30/minute")
async def upsert_metric(
    request: Request,
    project_id: str,
    body: UpsertMetricRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    metric = await _graph_svc.upsert_metric(
        db,
        project_id,
        body.name,
        connection_id=body.connection_id,
        display_name=body.display_name,
        description=body.description,
        category=body.category,
        source_table=body.source_table,
        source_column=body.source_column,
        aggregation=body.aggregation,
        formula=body.formula,
        unit=body.unit,
        data_type=body.data_type,
        discovery_source="user",
        confidence=0.9,
    )
    await db.commit()
    return {"id": metric.id, "name": metric.name}


@router.get("/{project_id}/relationships")
async def list_relationships(
    project_id: str,
    metric_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    rels = await _graph_svc.get_relationships(db, project_id, metric_id=metric_id)
    return [
        RelationshipResponse(
            id=r.id,
            metric_a_id=r.metric_a_id,
            metric_b_id=r.metric_b_id,
            relationship_type=r.relationship_type,
            strength=r.strength,
            direction=r.direction,
            description=r.description,
            confidence=r.confidence,
        )
        for r in rels
    ]


@router.post("/{project_id}/relationships")
@limiter.limit("30/minute")
async def add_relationship(
    request: Request,
    project_id: str,
    body: AddRelationshipRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    rel = await _graph_svc.add_relationship(
        db,
        project_id,
        body.metric_a_id,
        body.metric_b_id,
        body.relationship_type,
        strength=body.strength,
        direction=body.direction,
        description=body.description,
        evidence=body.evidence,
        confidence=body.confidence,
    )
    await db.commit()
    return {"id": rel.id}


@router.post("/{project_id}/discover/{connection_id}")
@limiter.limit("5/minute")
async def discover_metrics(
    request: Request,
    project_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    connection_id = validate_safe_id(connection_id, "connection_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    discovered = await _graph_svc.auto_discover_from_db_index(db, project_id, connection_id)
    await db.commit()
    return {"discovered_count": len(discovered)}


@router.delete("/{project_id}/metrics/{metric_id}")
@limiter.limit("20/minute")
async def delete_metric(
    request: Request,
    project_id: str,
    metric_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    project_id = validate_safe_id(project_id, "project_id")
    metric_id = validate_safe_id(metric_id, "metric_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    deleted = await _graph_svc.delete_metric(db, metric_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Metric not found")
    await db.commit()
    return {"deleted": True}
