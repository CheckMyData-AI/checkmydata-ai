"""Autonomous Insight Feed Agent.

Proactively scans connected data sources to discover anomalies, opportunities,
and patterns — without the user asking a question. Stores findings in the
Insight Memory Layer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.insight_generator import InsightGenerator
from app.core.insight_memory import InsightMemoryService
from app.core.trust_layer import TrustService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class FeedScanResult:
    """Result of an autonomous feed scan."""

    insights_created: int = 0
    insights_updated: int = 0
    queries_run: int = 0
    errors: list[str] = field(default_factory=list)


DIAGNOSTIC_QUERIES: list[dict[str, str]] = [
    {
        "name": "daily_trend",
        "description": "Recent daily activity trend",
        "template": (
            "SELECT DATE({date_col}) as day, COUNT(*) as count "
            "FROM {table} "
            "WHERE {date_col} >= DATE('now', '-30 days') "
            "GROUP BY DATE({date_col}) "
            "ORDER BY day"
        ),
    },
    {
        "name": "top_values",
        "description": "Top values by frequency",
        "template": (
            "SELECT {group_col}, COUNT(*) as cnt "
            "FROM {table} "
            "GROUP BY {group_col} "
            "ORDER BY cnt DESC "
            "LIMIT 20"
        ),
    },
]


class InsightFeedAgent:
    """Runs autonomous scans on connected data sources."""

    def __init__(self) -> None:
        self._memory = InsightMemoryService()
        self._trust = TrustService()
        self._insight_gen = InsightGenerator()

    async def run_scan(
        self,
        session: AsyncSession,
        project_id: str,
        connection_id: str,
        *,
        llm: LLMRouter | None = None,
        connector: Any = None,
        db_index_entries: list[Any] | None = None,
    ) -> FeedScanResult:
        """Execute a full scan cycle for one connection.

        Steps:
        1. Load DB index to identify key tables/columns
        2. Run diagnostic queries against the database
        3. Analyze results for insights (trends, outliers, etc.)
        4. Use LLM to generate deeper analysis if available
        5. Store findings in the Memory Layer
        """
        result = FeedScanResult()

        tables = db_index_entries or []
        if not tables:
            tables = await self._load_db_index(session, connection_id)

        if not tables:
            logger.info("No DB index for connection %s — skipping scan", connection_id)
            return result

        for entry in tables[:10]:
            try:
                insights = await self._analyze_table(
                    session,
                    project_id,
                    connection_id,
                    entry,
                    connector=connector,
                    llm=llm,
                )
                result.queries_run += 1
                for ins_data in insights:
                    record = await self._memory.store_insight(
                        session,
                        project_id,
                        ins_data["type"],
                        ins_data["title"],
                        ins_data["description"],
                        connection_id=connection_id,
                        severity=ins_data.get("severity", "info"),
                        confidence=ins_data.get("confidence", 0.5),
                        recommended_action=ins_data.get("action", ""),
                        expected_impact=ins_data.get("impact", ""),
                        trust_validation_method="auto_scan",
                        sample_size=ins_data.get("sample_size", 0),
                    )
                    if record.times_surfaced == 1:
                        result.insights_created += 1
                    else:
                        result.insights_updated += 1
            except Exception as exc:
                tbl = getattr(entry, "table_name", "?")
                logger.warning("Scan error for table %s: %s", tbl, exc)
                result.errors.append(str(exc))

        return result

    async def _load_db_index(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> list[Any]:
        from sqlalchemy import select

        from app.models.db_index import DbIndex

        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.is_active.is_(True),
            ).order_by(DbIndex.relevance_score.desc()).limit(10)
        )
        return list(result.scalars().all())

    async def _analyze_table(
        self,
        session: AsyncSession,
        project_id: str,
        connection_id: str,
        db_entry: Any,
        *,
        connector: Any = None,
        llm: LLMRouter | None = None,
    ) -> list[dict[str, Any]]:
        """Analyze a single table from the DB index and return insight dicts."""
        insights: list[dict[str, Any]] = []
        table_name = getattr(db_entry, "table_name", "")
        if not table_name:
            return insights

        try:
            col_notes = json.loads(db_entry.column_notes_json) if db_entry.column_notes_json else {}
        except (json.JSONDecodeError, TypeError):
            col_notes = {}

        sample_data = []
        try:
            sample_data = json.loads(db_entry.sample_data_json) if db_entry.sample_data_json else []
        except (json.JSONDecodeError, TypeError):
            sample_data = []

        if sample_data and col_notes:
            columns = list(col_notes.keys())[:20]
            rows = sample_data[:50] if isinstance(sample_data, list) else []
            if rows and columns:
                raw_insights = self._insight_gen.analyze(rows, columns)
                for raw in raw_insights:
                    insight_type = self._map_insight_type(raw.get("type", ""))
                    insights.append({
                        "type": insight_type,
                        "title": f"[{table_name}] {raw.get('title', 'Pattern detected')}",
                        "description": raw.get("description", ""),
                        "severity": self._map_severity(
                            raw.get("type", ""), raw.get("confidence", 0.5)
                        ),
                        "confidence": raw.get("confidence", 0.5),
                        "sample_size": len(rows),
                        "action": "",
                        "impact": "",
                    })

        if connector and llm:
            llm_insights = await self._llm_deep_analysis(
                table_name, col_notes, sample_data, llm
            )
            insights.extend(llm_insights)

        return insights

    async def _llm_deep_analysis(
        self,
        table_name: str,
        col_notes: dict[str, Any],
        sample_data: list[Any],
        llm: LLMRouter,
    ) -> list[dict[str, Any]]:
        """Use LLM to generate deeper insights from table metadata."""
        try:
            from app.llm.base import Message

            prompt = (
                f"Analyze this database table and identify any business insights:\n"
                f"Table: {table_name}\n"
                f"Columns: {json.dumps(list(col_notes.keys())[:15])}\n"
                f"Sample rows: {json.dumps(sample_data[:5])}\n\n"
                f"Return a JSON array of insights, each with: "
                f"type (anomaly|opportunity|loss|trend|pattern|observation), "
                f"title, description, severity (critical|warning|info|positive), "
                f"confidence (0-1), action (what to do), impact (expected result).\n"
                f"Return [] if no significant insights found."
            )

            response = await llm.complete(
                messages=[Message(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=1000,
            )

            if response and response.content:
                content = response.content.strip()
                if content.startswith("["):
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        valid = []
                        for item in parsed[:5]:
                            if isinstance(item, dict) and "title" in item:
                                valid.append({
                                    "type": item.get("type", "observation"),
                                    "title": f"[{table_name}] {item['title']}",
                                    "description": item.get("description", ""),
                                    "severity": item.get("severity", "info"),
                                    "confidence": min(0.7, float(item.get("confidence", 0.5))),
                                    "action": item.get("action", ""),
                                    "impact": item.get("impact", ""),
                                    "sample_size": len(content),
                                })
                        return valid
        except Exception as exc:
            logger.debug("LLM deep analysis failed for %s: %s", table_name, exc)
        return []

    @staticmethod
    def _map_insight_type(raw_type: str) -> str:
        if raw_type.startswith("trend_"):
            return "trend"
        mapping = {
            "outlier": "anomaly",
            "concentration": "pattern",
            "summary": "observation",
        }
        return mapping.get(raw_type, "observation")

    @staticmethod
    def _map_severity(raw_type: str, confidence: float) -> str:
        if raw_type == "outlier" and confidence > 0.7:
            return "warning"
        if raw_type.startswith("trend_") and confidence > 0.8:
            return "warning"
        if raw_type == "concentration" and confidence > 0.7:
            return "info"
        return "info"
