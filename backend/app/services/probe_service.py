"""Proactive data health probes run after initial DB indexing.

Executes simple validation queries on the top tables and creates
session notes for any anomalies discovered (e.g. high NULL rates,
suspicious value distributions, empty tables).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from app.connectors.base import ConnectionConfig
from app.connectors.registry import get_connector
from app.core.anomaly_intelligence import AnomalyIntelligenceEngine
from app.core.data_sanity_checker import DataSanityChecker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_PROBE_TABLES = 5
MAX_PROBE_ROWS = 50


class ProbeService:
    """Run lightweight probe queries to assess data health."""

    async def run_probes(
        self,
        session: AsyncSession,
        connection_id: str,
        project_id: str,
        cfg: ConnectionConfig,
        table_names: list[str],
    ) -> list[dict[str, Any]]:
        """Probe the top *table_names* and return a health report."""
        from app.services.session_notes_service import SessionNotesService

        notes_svc = SessionNotesService()
        checker = DataSanityChecker()
        anomaly_engine = AnomalyIntelligenceEngine()
        report: list[dict[str, Any]] = []

        tables_to_probe = table_names[:MAX_PROBE_TABLES]

        connector = get_connector(
            cfg.db_type,
            ssh_exec_mode=cfg.ssh_exec_mode,
        )
        await connector.connect(cfg)

        try:
            for table in tables_to_probe:
                entry = await self._probe_table(
                    connector,
                    table,
                    checker,
                    anomaly_engine,
                )
                report.append(entry)

                for finding in entry.get("findings", []):
                    await notes_svc.create_note(
                        session,
                        connection_id=connection_id,
                        project_id=project_id,
                        category="data_observation",
                        subject=table,
                        note=finding,
                        confidence=0.6,
                    )
        finally:
            await connector.disconnect()

        await session.flush()
        return report

    _VALID_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.\"` \-]{0,200}$")

    async def _probe_table(
        self,
        connector: Any,
        table: str,
        checker: DataSanityChecker,
        anomaly_engine: AnomalyIntelligenceEngine | None = None,
    ) -> dict[str, Any]:
        """Run diagnostics on a single table."""
        entry: dict[str, Any] = {
            "table": table,
            "findings": [],
            "anomaly_reports": [],
            "row_count": None,
            "null_rates": {},
        }

        if not self._VALID_TABLE_RE.match(table):
            entry["findings"].append(f"Skipped: invalid table name '{table}'")
            return entry

        quoted = f'"{table}"' if '"' not in table else table

        try:
            count_result = await connector.execute_query(f"SELECT COUNT(*) AS cnt FROM {quoted}")
            if count_result.rows:
                entry["row_count"] = count_result.rows[0][0]
                if entry["row_count"] == 0:
                    entry["findings"].append(f"Table '{table}' is empty (0 rows).")
                    return entry
        except Exception as exc:
            entry["findings"].append(f"Could not count rows in '{table}': {exc}")
            return entry

        try:
            sample_result = await connector.execute_query(
                f"SELECT * FROM {quoted} LIMIT {MAX_PROBE_ROWS}"
            )
            if not sample_result.rows:
                return entry

            rows_as_dicts = [dict(zip(sample_result.columns, row)) for row in sample_result.rows]

            for col in sample_result.columns:
                total = len(rows_as_dicts)
                nulls = sum(1 for r in rows_as_dicts if r.get(col) is None)
                if total > 0:
                    rate = nulls / total
                    entry["null_rates"][col] = round(rate, 2)
                    if rate >= 0.8:
                        entry["findings"].append(
                            f"Column '{table}.{col}' has "
                            f"{int(rate * 100)}% NULL values "
                            f"({nulls}/{total} sampled rows)."
                        )

            warnings = checker.check(
                rows=rows_as_dicts,
                columns=sample_result.columns,
            )
            for w in warnings:
                entry["findings"].append(f"[{w.check_type}] {w.message}")

            if anomaly_engine:
                reports = anomaly_engine.analyze(
                    rows=rows_as_dicts,
                    columns=sample_result.columns,
                )
                entry["anomaly_reports"] = [r.to_dict() for r in reports]

        except Exception as exc:
            entry["findings"].append(f"Probe query failed for '{table}': {exc}")

        return entry
