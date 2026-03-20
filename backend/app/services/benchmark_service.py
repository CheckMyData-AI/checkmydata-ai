"""Benchmark store for verified metric values used in sanity checking."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.benchmark import DataBenchmark

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def normalize_metric_key(raw: str) -> str:
    """Normalise metric descriptions into comparable keys.

    ``"Total Revenue for March 2024"`` → ``"total_revenue_march_2024"``
    """
    key = raw.strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key


class BenchmarkService:
    """Manages known-good metric benchmarks per connection."""

    async def find_benchmark(
        self,
        session: AsyncSession,
        connection_id: str,
        metric_key: str | None = None,
        raw_description: str | None = None,
    ) -> DataBenchmark | None:
        if metric_key:
            key = metric_key
        elif raw_description:
            key = normalize_metric_key(raw_description)
        else:
            return None

        result = await session.execute(
            select(DataBenchmark)
            .where(
                DataBenchmark.connection_id == connection_id,
                DataBenchmark.metric_key == key,
            )
            .order_by(DataBenchmark.last_confirmed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_or_confirm(
        self,
        session: AsyncSession,
        connection_id: str,
        metric_key: str,
        value: str,
        value_numeric: float | None = None,
        unit: str | None = None,
        source: str = "agent_derived",
        metric_description: str = "",
    ) -> DataBenchmark:
        key = normalize_metric_key(metric_key) if " " in metric_key else metric_key

        existing = await self.find_benchmark(session, connection_id, metric_key=key)
        if existing:
            existing.times_confirmed += 1
            existing.confidence = min(1.0, existing.confidence + 0.1)
            existing.last_confirmed_at = datetime.now(UTC)
            if source == "user_confirmed" and existing.source != "user_confirmed":
                existing.source = "user_confirmed"
            if value_numeric is not None:
                existing.value_numeric = value_numeric
            existing.value = value
            await session.flush()
            return existing

        entry = DataBenchmark(
            connection_id=connection_id,
            metric_key=key,
            metric_description=metric_description or metric_key,
            value=value,
            value_numeric=value_numeric,
            unit=unit,
            source=source,
            confidence=0.8 if source == "user_confirmed" else 0.5,
        )
        session.add(entry)
        await session.flush()
        return entry

    async def flag_stale(
        self,
        session: AsyncSession,
        connection_id: str,
        metric_key: str,
    ) -> DataBenchmark | None:
        bm = await self.find_benchmark(session, connection_id, metric_key=metric_key)
        if not bm:
            return None
        bm.confidence = max(0.0, bm.confidence - 0.3)
        await session.flush()
        return bm

    async def get_all_for_connection(
        self,
        session: AsyncSession,
        connection_id: str,
        min_confidence: float = 0.3,
    ) -> list[DataBenchmark]:
        result = await session.execute(
            select(DataBenchmark)
            .where(
                DataBenchmark.connection_id == connection_id,
                DataBenchmark.confidence >= min_confidence,
            )
            .order_by(DataBenchmark.last_confirmed_at.desc())
        )
        return list(result.scalars().all())
