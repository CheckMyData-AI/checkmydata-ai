"""Data Graph — unified registry of metrics, sources, and relationships.

The graph is built from DB index metadata and enriched over time as the system
discovers relationships between metrics via queries, insights, and user feedback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from app.models.metric_definition import MetricDefinition, MetricRelationship

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

VALID_RELATIONSHIP_TYPES = frozenset(
    {
        "correlation",
        "dependency",
        "causation_hypothesis",
        "foreign_key",
        "derived_from",
        "same_entity",
    }
)

VALID_METRIC_CATEGORIES = frozenset(
    {
        "revenue",
        "cost",
        "conversion",
        "engagement",
        "retention",
        "acquisition",
        "performance",
        "general",
    }
)


@dataclass
class GraphNode:
    """In-memory representation of a metric node in the graph."""

    metric_id: str
    name: str
    display_name: str
    category: str
    source_table: str | None
    connection_id: str | None
    confidence: float
    edges: list[GraphEdge] = field(default_factory=list)


@dataclass
class GraphEdge:
    """In-memory representation of a relationship edge."""

    target_id: str
    relationship_type: str
    strength: float
    direction: str
    confidence: float


class DataGraphService:
    """CRUD and graph-building operations for the metric registry."""

    async def upsert_metric(
        self,
        session: AsyncSession,
        project_id: str,
        name: str,
        *,
        connection_id: str | None = None,
        display_name: str = "",
        description: str = "",
        category: str = "general",
        source_table: str | None = None,
        source_column: str | None = None,
        aggregation: str = "",
        formula: str = "",
        unit: str = "",
        data_type: str = "numeric",
        discovery_source: str = "auto",
        confidence: float = 0.5,
    ) -> MetricDefinition:
        result = await session.execute(
            select(MetricDefinition).where(
                MetricDefinition.project_id == project_id,
                MetricDefinition.name == name,
                MetricDefinition.connection_id == connection_id
                if connection_id
                else MetricDefinition.connection_id.is_(None),
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.display_name = display_name or existing.display_name
            existing.description = description or existing.description
            existing.category = category if category != "general" else existing.category
            existing.source_table = source_table or existing.source_table
            existing.source_column = source_column or existing.source_column
            existing.aggregation = aggregation or existing.aggregation
            existing.formula = formula or existing.formula
            existing.unit = unit or existing.unit
            existing.confidence = max(existing.confidence, confidence)
            existing.times_referenced += 1
            await session.flush()
            return existing

        metric = MetricDefinition(
            project_id=project_id,
            connection_id=connection_id,
            name=name,
            display_name=display_name or name.replace("_", " ").title(),
            description=description,
            category=category,
            source_table=source_table,
            source_column=source_column,
            aggregation=aggregation,
            formula=formula,
            unit=unit,
            data_type=data_type,
            discovery_source=discovery_source,
            confidence=confidence,
        )
        session.add(metric)
        await session.flush()
        return metric

    async def add_relationship(
        self,
        session: AsyncSession,
        project_id: str,
        metric_a_id: str,
        metric_b_id: str,
        relationship_type: str,
        *,
        strength: float = 0.0,
        direction: str = "bidirectional",
        description: str = "",
        evidence: str = "",
        confidence: float = 0.5,
    ) -> MetricRelationship:
        if relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(f"Invalid relationship_type: {relationship_type}")

        result = await session.execute(
            select(MetricRelationship).where(
                MetricRelationship.metric_a_id == metric_a_id,
                MetricRelationship.metric_b_id == metric_b_id,
                MetricRelationship.relationship_type == relationship_type,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.strength = max(existing.strength, strength)
            existing.confidence = max(existing.confidence, confidence)
            if evidence:
                existing.evidence = evidence
            await session.flush()
            return existing

        rel = MetricRelationship(
            project_id=project_id,
            metric_a_id=metric_a_id,
            metric_b_id=metric_b_id,
            relationship_type=relationship_type,
            strength=strength,
            direction=direction,
            description=description,
            evidence=evidence,
            confidence=confidence,
        )
        session.add(rel)
        await session.flush()
        return rel

    async def get_metrics(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        connection_id: str | None = None,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[MetricDefinition]:
        stmt = select(MetricDefinition).where(MetricDefinition.project_id == project_id)
        if connection_id:
            stmt = stmt.where(MetricDefinition.connection_id == connection_id)
        if category:
            stmt = stmt.where(MetricDefinition.category == category)
        if active_only:
            stmt = stmt.where(MetricDefinition.is_active.is_(True))
        stmt = stmt.order_by(
            MetricDefinition.confidence.desc(), MetricDefinition.times_referenced.desc()
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_metric_by_id(
        self,
        session: AsyncSession,
        metric_id: str,
    ) -> MetricDefinition | None:
        return await session.get(MetricDefinition, metric_id)

    async def get_relationships(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        metric_id: str | None = None,
    ) -> list[MetricRelationship]:
        stmt = select(MetricRelationship).where(MetricRelationship.project_id == project_id)
        if metric_id:
            stmt = stmt.where(
                (MetricRelationship.metric_a_id == metric_id)
                | (MetricRelationship.metric_b_id == metric_id)
            )
        stmt = stmt.order_by(MetricRelationship.strength.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def build_graph(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> dict[str, GraphNode]:
        """Build an in-memory graph of all metrics and their relationships."""
        metrics = await self.get_metrics(session, project_id)
        relationships = await self.get_relationships(session, project_id)

        nodes: dict[str, GraphNode] = {}
        for m in metrics:
            nodes[m.id] = GraphNode(
                metric_id=m.id,
                name=m.name,
                display_name=m.display_name,
                category=m.category,
                source_table=m.source_table,
                connection_id=m.connection_id,
                confidence=m.confidence,
            )

        for rel in relationships:
            if rel.metric_a_id in nodes:
                nodes[rel.metric_a_id].edges.append(
                    GraphEdge(
                        target_id=rel.metric_b_id,
                        relationship_type=rel.relationship_type,
                        strength=rel.strength,
                        direction=rel.direction,
                        confidence=rel.confidence,
                    )
                )
            if rel.metric_b_id in nodes and rel.direction == "bidirectional":
                nodes[rel.metric_b_id].edges.append(
                    GraphEdge(
                        target_id=rel.metric_a_id,
                        relationship_type=rel.relationship_type,
                        strength=rel.strength,
                        direction=rel.direction,
                        confidence=rel.confidence,
                    )
                )

        return nodes

    async def get_graph_summary(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> dict[str, Any]:
        """Return a JSON-serializable summary of the data graph."""
        metric_count = await session.execute(
            select(func.count(MetricDefinition.id)).where(
                MetricDefinition.project_id == project_id,
                MetricDefinition.is_active.is_(True),
            )
        )
        rel_count = await session.execute(
            select(func.count(MetricRelationship.id)).where(
                MetricRelationship.project_id == project_id
            )
        )

        cat_result = await session.execute(
            select(MetricDefinition.category, func.count(MetricDefinition.id))
            .where(
                MetricDefinition.project_id == project_id,
                MetricDefinition.is_active.is_(True),
            )
            .group_by(MetricDefinition.category)
        )

        return {
            "total_metrics": metric_count.scalar_one(),
            "total_relationships": rel_count.scalar_one(),
            "categories": {cat: cnt for cat, cnt in cat_result.all()},
        }

    async def delete_metric(
        self,
        session: AsyncSession,
        metric_id: str,
    ) -> bool:
        metric = await session.get(MetricDefinition, metric_id)
        if not metric:
            return False
        await session.execute(
            delete(MetricRelationship).where(
                (MetricRelationship.metric_a_id == metric_id)
                | (MetricRelationship.metric_b_id == metric_id)
            )
        )
        await session.delete(metric)
        await session.flush()
        return True

    async def auto_discover_from_db_index(
        self,
        session: AsyncSession,
        project_id: str,
        connection_id: str,
    ) -> list[MetricDefinition]:
        """Extract potential metrics from the DB index entries for a connection."""
        from app.models.db_index import DbIndex

        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.is_active.is_(True),
            )
        )
        db_entries = result.scalars().all()

        discovered: list[MetricDefinition] = []
        metric_hints = {
            "revenue",
            "sales",
            "amount",
            "price",
            "cost",
            "total",
            "count",
            "quantity",
            "rate",
            "ratio",
            "score",
            "balance",
            "profit",
            "fee",
            "users",
            "views",
            "clicks",
            "conversions",
            "orders",
            "visits",
            "sessions",
            "signups",
            "churned",
            "active",
            "retention",
        }

        for entry in db_entries:
            try:
                col_notes = json.loads(entry.column_notes_json) if entry.column_notes_json else {}
            except (json.JSONDecodeError, TypeError):
                col_notes = {}

            for col_name, note in col_notes.items():
                col_lower = col_name.lower()
                if any(hint in col_lower for hint in metric_hints):
                    category = self._guess_category(col_lower)
                    metric = await self.upsert_metric(
                        session,
                        project_id,
                        name=f"{entry.table_name}.{col_name}",
                        connection_id=connection_id,
                        description=note if isinstance(note, str) else "",
                        category=category,
                        source_table=entry.table_name,
                        source_column=col_name,
                        discovery_source="db_index",
                        confidence=0.4,
                    )
                    discovered.append(metric)

        return discovered

    @staticmethod
    def _guess_category(col_name: str) -> str:
        revenue_hints = {"revenue", "sales", "amount", "price", "profit", "fee"}
        cost_hints = {"cost", "expense", "spend"}
        conversion_hints = {"conversion", "rate", "ratio", "clicks", "ctr"}
        engagement_hints = {"views", "visits", "sessions", "active", "engagement"}
        retention_hints = {"retention", "churned", "churn", "returning"}
        acquisition_hints = {"signups", "acquisition", "new_users", "registrations"}

        for hint in revenue_hints:
            if hint in col_name:
                return "revenue"
        for hint in cost_hints:
            if hint in col_name:
                return "cost"
        for hint in conversion_hints:
            if hint in col_name:
                return "conversion"
        for hint in engagement_hints:
            if hint in col_name:
                return "engagement"
        for hint in retention_hints:
            if hint in col_name:
                return "retention"
        for hint in acquisition_hints:
            if hint in col_name:
                return "acquisition"
        return "general"
