"""Semantic Layer Auto-Build.

Automatically discovers metrics from DB index entries, normalizes
definitions across connections, infers aggregation logic, and
maintains a unified metric catalog in the Data Graph.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import sqlalchemy.exc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NUMERIC_TYPES = frozenset(
    {
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "float",
        "double",
        "decimal",
        "numeric",
        "real",
        "money",
        "number",
    }
)

AGGREGATION_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"(revenue|sales|amount|price|total|fee|cost|profit|balance)"), "SUM", "revenue"),
    (re.compile(r"(count|quantity|num_|number_of)"), "SUM", "general"),
    (re.compile(r"(rate|ratio|pct|percent|score|avg_|average)"), "AVG", "conversion"),
    (re.compile(r"(users|customers|visitors|sessions|views|clicks|orders)"), "COUNT", "engagement"),
    (re.compile(r"(churn|retention|returning)"), "AVG", "retention"),
    (re.compile(r"(signup|registration|acquisition|new_user)"), "COUNT", "acquisition"),
    (re.compile(r"(spend|expense|budget|ad_cost)"), "SUM", "cost"),
]

UNIT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(revenue|sales|amount|price|fee|cost|profit|balance|spend)"), "$"),
    (re.compile(r"(rate|ratio|pct|percent|conversion)"), "%"),
    (re.compile(r"(users|customers|visitors|orders|count|sessions|views|clicks)"), "count"),
    (re.compile(r"(seconds|duration|latency|time_ms|response_time)"), "ms"),
    (re.compile(r"(bytes|size|memory)"), "bytes"),
]

CANONICAL_NAMES: dict[str, str] = {
    "total_revenue": "revenue",
    "gross_revenue": "revenue",
    "net_revenue": "revenue",
    "total_sales": "revenue",
    "total_amount": "revenue",
    "user_count": "users",
    "total_users": "users",
    "active_users": "active_users",
    "monthly_active_users": "active_users",
    "mau": "active_users",
    "daily_active_users": "daily_active_users",
    "dau": "daily_active_users",
    "total_orders": "orders",
    "order_count": "orders",
    "num_orders": "orders",
    "conversion_rate": "conversion_rate",
    "cvr": "conversion_rate",
    "churn_rate": "churn_rate",
    "retention_rate": "retention_rate",
    "cac": "customer_acquisition_cost",
    "customer_acquisition_cost": "customer_acquisition_cost",
    "ltv": "lifetime_value",
    "lifetime_value": "lifetime_value",
    "customer_lifetime_value": "lifetime_value",
    "clv": "lifetime_value",
    "arpu": "arpu",
    "average_revenue_per_user": "arpu",
    "mrr": "monthly_recurring_revenue",
    "monthly_recurring_revenue": "monthly_recurring_revenue",
    "arr": "annual_recurring_revenue",
    "annual_recurring_revenue": "annual_recurring_revenue",
    "ad_spend": "ad_spend",
    "advertising_spend": "ad_spend",
    "total_spend": "ad_spend",
    "ctr": "click_through_rate",
    "click_through_rate": "click_through_rate",
    "cpc": "cost_per_click",
    "cost_per_click": "cost_per_click",
    "bounce_rate": "bounce_rate",
    "page_views": "page_views",
    "pageviews": "page_views",
    "signups": "signups",
    "registrations": "signups",
    "new_users": "signups",
}


@dataclass
class MetricCandidate:
    """A candidate metric discovered from DB schema analysis."""

    name: str
    display_name: str
    canonical_name: str
    description: str
    category: str
    source_table: str
    source_column: str
    aggregation: str
    unit: str
    data_type: str
    confidence: float
    connection_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizationResult:
    """Result of cross-connection metric normalization."""

    canonical_name: str
    display_name: str
    variants: list[dict[str, str]] = field(default_factory=list)
    category: str = "general"
    aggregation: str = ""
    unit: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticLayerService:
    """Builds and maintains a semantic layer of normalized metrics."""

    def discover_metrics_from_index(
        self,
        db_index_entries: list[dict[str, Any]],
        connection_id: str | None = None,
    ) -> list[MetricCandidate]:
        """Analyze DB index entries and discover metric candidates.

        Each entry is expected to have: table_name, column_notes_json,
        column_distinct_values_json, business_description, data_patterns.
        """
        candidates: list[MetricCandidate] = []

        for entry in db_index_entries:
            table_name = entry.get("table_name", "")
            col_notes = self._parse_json(entry.get("column_notes_json", "{}"))
            col_distinct = self._parse_json(entry.get("column_distinct_values_json", "{}"))
            biz_desc = entry.get("business_description", "")

            for col_name, note in col_notes.items():
                col_lower = col_name.lower()
                agg, category = self._infer_aggregation(col_lower)
                unit = self._infer_unit(col_lower)
                data_type = self._infer_data_type(col_lower, col_distinct.get(col_name))
                canonical = self._normalize_name(col_lower)
                confidence = self._estimate_confidence(col_lower, note, data_type, agg)

                if confidence <= 0.3:
                    continue

                display = col_name.replace("_", " ").title()
                desc = note if isinstance(note, str) else ""
                if biz_desc and not desc:
                    desc = f"From table: {biz_desc}"

                candidates.append(
                    MetricCandidate(
                        name=f"{table_name}.{col_name}",
                        display_name=display,
                        canonical_name=canonical,
                        description=desc,
                        category=category,
                        source_table=table_name,
                        source_column=col_name,
                        aggregation=agg,
                        unit=unit,
                        data_type=data_type,
                        confidence=confidence,
                        connection_id=connection_id,
                    )
                )

        return candidates

    def normalize_across_connections(
        self,
        all_candidates: list[MetricCandidate],
    ) -> list[NormalizationResult]:
        """Group metric candidates by canonical name across connections."""
        groups: dict[str, list[MetricCandidate]] = {}
        for c in all_candidates:
            groups.setdefault(c.canonical_name, []).append(c)

        results: list[NormalizationResult] = []
        for canonical, members in sorted(groups.items()):
            best = max(members, key=lambda m: m.confidence)
            variants = [
                {
                    "name": m.name,
                    "connection_id": m.connection_id or "",
                    "source_table": m.source_table,
                    "source_column": m.source_column,
                }
                for m in members
            ]
            results.append(
                NormalizationResult(
                    canonical_name=canonical,
                    display_name=best.display_name,
                    variants=variants,
                    category=best.category,
                    aggregation=best.aggregation,
                    unit=best.unit,
                    confidence=min(best.confidence + 0.1 * (len(members) - 1), 0.95),
                )
            )

        return results

    async def build_catalog(
        self,
        session: AsyncSession,
        project_id: str,
        connection_id: str,
    ) -> list[MetricCandidate]:
        """Build the semantic catalog for a connection using DB index data."""
        from sqlalchemy import select

        from app.models.db_index import DbIndex

        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.is_active.is_(True),
            )
        )
        entries = [
            {
                "table_name": e.table_name,
                "column_notes_json": e.column_notes_json,
                "column_distinct_values_json": e.column_distinct_values_json,
                "business_description": e.business_description,
                "data_patterns": e.data_patterns,
            }
            for e in result.scalars().all()
        ]

        candidates = self.discover_metrics_from_index(entries, connection_id)

        from app.core.data_graph import DataGraphService

        graph_svc = DataGraphService()
        for c in candidates:
            await graph_svc.upsert_metric(
                session,
                project_id,
                c.name,
                connection_id=connection_id,
                display_name=c.display_name,
                description=c.description,
                category=c.category,
                source_table=c.source_table,
                source_column=c.source_column,
                aggregation=c.aggregation,
                unit=c.unit,
                data_type=c.data_type,
                discovery_source="semantic_layer",
                confidence=c.confidence,
            )

        await session.commit()
        return candidates

    async def normalize_project(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[NormalizationResult]:
        """Normalize metrics across all connections in a project."""
        from app.core.data_graph import DataGraphService

        graph_svc = DataGraphService()
        metrics = await graph_svc.get_metrics(session, project_id)

        candidates = [
            MetricCandidate(
                name=m.name,
                display_name=m.display_name,
                canonical_name=self._normalize_name(m.name.split(".")[-1].lower()),
                description=m.description,
                category=m.category,
                source_table=m.source_table or "",
                source_column=m.source_column or "",
                aggregation=m.aggregation,
                unit=m.unit,
                data_type=m.data_type,
                confidence=m.confidence,
                connection_id=m.connection_id,
            )
            for m in metrics
        ]

        normalized = self.normalize_across_connections(candidates)

        for norm in normalized:
            if len(norm.variants) > 1:
                metric_ids = []
                for variant in norm.variants:
                    from sqlalchemy import select

                    from app.models.metric_definition import MetricDefinition

                    result = await session.execute(
                        select(MetricDefinition.id).where(
                            MetricDefinition.project_id == project_id,
                            MetricDefinition.name == variant["name"],
                        )
                    )
                    mid = result.scalar_one_or_none()
                    if mid:
                        metric_ids.append(mid)

                for i in range(len(metric_ids)):
                    for j in range(i + 1, len(metric_ids)):
                        try:
                            await graph_svc.add_relationship(
                                session,
                                project_id,
                                metric_ids[i],
                                metric_ids[j],
                                "same_entity",
                                strength=norm.confidence,
                                description=(
                                    f"Both map to canonical metric: {norm.canonical_name}"
                                ),
                                confidence=norm.confidence,
                            )
                        except (ValueError, KeyError, sqlalchemy.exc.IntegrityError):
                            logger.debug(
                                "Failed to add same_entity relationship",
                                exc_info=True,
                            )

        await session.commit()
        return normalized

    def _infer_aggregation(self, col_name: str) -> tuple[str, str]:
        for pattern, agg, category in AGGREGATION_HINTS:
            if pattern.search(col_name):
                return agg, category
        return "", "general"

    def _infer_unit(self, col_name: str) -> str:
        for pattern, unit in UNIT_HINTS:
            if pattern.search(col_name):
                return unit
        return ""

    def _infer_data_type(self, col_name: str, distinct_values: Any = None) -> str:
        if distinct_values and isinstance(distinct_values, list):
            if all(isinstance(v, (int, float)) for v in distinct_values[:10]):
                return "numeric"
            if all(isinstance(v, str) for v in distinct_values[:10]):
                return "text"
        if any(kw in col_name for kw in ("id", "name", "email", "status", "type", "label")):
            return "text"
        return "numeric"

    def _normalize_name(self, col_name: str) -> str:
        clean = re.sub(r"^(total_|sum_|avg_|count_|num_|n_)", "", col_name)
        clean = re.sub(r"(_total|_sum|_count|_avg)$", "", clean)
        return CANONICAL_NAMES.get(col_name, CANONICAL_NAMES.get(clean, clean))

    def _estimate_confidence(
        self,
        col_name: str,
        note: Any,
        data_type: str,
        aggregation: str,
    ) -> float:
        score = 0.3
        if aggregation:
            score += 0.2
        if data_type == "numeric":
            score += 0.1
        if isinstance(note, str) and len(note) > 10:
            score += 0.1
        if col_name in CANONICAL_NAMES:
            score += 0.15
        for pattern, _, _ in AGGREGATION_HINTS:
            if pattern.search(col_name):
                score += 0.1
                break
        return min(score, 0.95)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw) if raw else {}
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
