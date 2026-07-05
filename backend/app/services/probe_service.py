"""Proactive data health probes run after initial DB indexing.

Executes simple validation queries on the top tables and creates
session notes for any anomalies discovered (e.g. high NULL rates,
suspicious value distributions, empty tables).

Dialect-awareness (DBIDX-D3)
-----------------------------
``_probe_table`` routes through dialect-aware connector methods so that
non-SQL connectors (MongoDB) are never sent raw SQL strings:

* **Sample rows** — always via ``connector.sample_data(table, MAX_PROBE_ROWS)``.
  Every DatabaseAdapter already implements this; MongoDB overrides it to issue
  a native ``find`` spec.

* **Row count** — branched on ``connector.db_type``:
  - ``mongodb``: ``execute_query(json_spec)`` where the spec uses
    ``"operation": "count"`` (MongoDB's connector handles this natively).
  - All SQL dialects: ``execute_query("SELECT COUNT(*) AS cnt FROM {quoted}")``.
    Identifier quoting is dialect-aware (backtick for MySQL, double-quote for
    others) so the count query is also valid for every SQL backend.
"""

from __future__ import annotations

import json
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

    _VALID_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_. \-]{0,200}$")

    @staticmethod
    def _quote_identifier(name: str, db_type: str = "") -> str:
        """Quote a SQL identifier using the dialect-appropriate quoting style.

        MySQL uses backtick quoting; all other SQL dialects use standard
        double-quote (ANSI SQL).  MongoDB does not use this helper — its
        count path sends a JSON spec instead.
        """
        if db_type == "mysql":
            escaped = name.replace("`", "``")
            return f"`{escaped}`"
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    async def _count_rows(self, connector: Any, table: str) -> Any:
        """Issue a dialect-appropriate row-count query and return the count value.

        - **MongoDB**: sends a JSON spec ``{"collection": table, "operation":
          "count", "filter": {}}`` through ``execute_query`` — the MongoDB
          connector handles this natively without touching any SQL parser.
        - **SQL dialects** (PostgreSQL, MySQL, ClickHouse, …): issues
          ``SELECT COUNT(*) AS cnt FROM {quoted}`` with dialect-aware identifier
          quoting (backtick for MySQL, double-quote otherwise).

        Returns the raw count value, or raises on any execution error.
        """
        db_type: str = getattr(connector, "db_type", "")
        if db_type == "mongodb":
            spec = json.dumps({"collection": table, "operation": "count", "filter": {}})
            result = await connector.execute_query(spec)
        else:
            quoted = self._quote_identifier(table, db_type)
            result = await connector.execute_query(f"SELECT COUNT(*) AS cnt FROM {quoted}")
        if result.error:
            raise RuntimeError(result.error)
        if not result.rows:
            return None
        return result.rows[0][0]

    async def _probe_table(
        self,
        connector: Any,
        table: str,
        checker: DataSanityChecker,
        anomaly_engine: AnomalyIntelligenceEngine | None = None,
    ) -> dict[str, Any]:
        """Run diagnostics on a single table.

        Routing logic (DBIDX-D3):
        - Row count  → ``_count_rows`` (dialect-aware, see docstring there).
        - Sample rows → ``connector.sample_data(table, MAX_PROBE_ROWS)``
          (every DatabaseAdapter implements this; MongoDB overrides it natively).
        """
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

        try:
            count = await self._count_rows(connector, table)
            entry["row_count"] = count
            if count == 0:
                entry["findings"].append(f"Table '{table}' is empty (0 rows).")
                return entry
        except Exception as exc:
            entry["findings"].append(f"Could not count rows in '{table}': {exc}")
            return entry

        try:
            sample_result = await connector.sample_data(table, MAX_PROBE_ROWS)
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
