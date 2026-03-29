"""API routes for Semantic Layer Auto-Build."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.rate_limit import limiter
from app.core.semantic_layer import SemanticLayerService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["semantic-layer"])

_membership_svc = MembershipService()
_semantic_svc = SemanticLayerService()


@router.post("/{project_id}/build/{connection_id}")
@limiter.limit("10/minute")
async def build_catalog(
    request: Request,
    project_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Build the semantic catalog for a connection from DB index data."""
    project_id = validate_safe_id(project_id, "project_id")
    connection_id = validate_safe_id(connection_id, "connection_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

    candidates = await _semantic_svc.build_catalog(db, project_id, connection_id)

    return {
        "connection_id": connection_id,
        "metrics_discovered": len(candidates),
        "metrics": [c.to_dict() for c in candidates],
    }


@router.post("/{project_id}/normalize")
@limiter.limit("10/minute")
async def normalize_project(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Normalize metrics across all connections in a project."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

    results = await _semantic_svc.normalize_project(db, project_id)

    return {
        "canonical_metrics": len(results),
        "cross_connection": sum(1 for r in results if len(r.variants) > 1),
        "results": [r.to_dict() for r in results],
    }


@router.get("/{project_id}/catalog")
async def get_catalog(
    project_id: str,
    connection_id: str | None = None,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Browse the metric catalog."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from app.core.data_graph import DataGraphService

    graph_svc = DataGraphService()
    metrics = await graph_svc.get_metrics(
        db,
        project_id,
        connection_id=connection_id,
        category=category,
    )

    return {
        "total": len(metrics),
        "metrics": [
            {
                "id": m.id,
                "name": m.name,
                "display_name": m.display_name,
                "description": m.description,
                "category": m.category,
                "source_table": m.source_table,
                "source_column": m.source_column,
                "aggregation": m.aggregation,
                "formula": m.formula,
                "unit": m.unit,
                "data_type": m.data_type,
                "confidence": m.confidence,
                "connection_id": m.connection_id,
                "discovery_source": m.discovery_source,
                "times_referenced": m.times_referenced,
            }
            for m in metrics
        ],
    }
