"""CRUD and formatting for database index entries."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.models.db_index import DbIndex, DbIndexSummary

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DbIndexService:
    # ------------------------------------------------------------------
    # Per-table CRUD
    # ------------------------------------------------------------------

    async def upsert_table(
        self,
        session: AsyncSession,
        connection_id: str,
        table_data: dict,
    ) -> DbIndex:
        table_name = table_data["table_name"]
        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.table_name == table_name,
            )
        )
        entry = result.scalar_one_or_none()

        if entry:
            for key, value in table_data.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.indexed_at = datetime.now(UTC)
            entry.updated_at = datetime.now(UTC)
        else:
            entry = DbIndex(connection_id=connection_id, **table_data)
            session.add(entry)

        await session.flush()
        return entry

    async def get_index(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> list[DbIndex]:
        result = await session.execute(
            select(DbIndex)
            .where(DbIndex.connection_id == connection_id)
            .order_by(DbIndex.relevance_score.desc(), DbIndex.table_name)
        )
        return list(result.scalars().all())

    async def get_table_index(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
    ) -> DbIndex | None:
        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.table_name == table_name,
            )
        )
        return result.scalar_one_or_none()

    async def delete_stale_tables(
        self,
        session: AsyncSession,
        connection_id: str,
        current_table_names: set[str],
    ) -> int:
        result = await session.execute(
            select(DbIndex).where(DbIndex.connection_id == connection_id)
        )
        all_entries = result.scalars().all()
        deleted = 0
        for entry in all_entries:
            if entry.table_name not in current_table_names:
                await session.delete(entry)
                deleted += 1
        if deleted:
            await session.flush()
        return deleted

    async def delete_all(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> None:
        await session.execute(delete(DbIndex).where(DbIndex.connection_id == connection_id))
        await session.execute(
            delete(DbIndexSummary).where(DbIndexSummary.connection_id == connection_id)
        )
        await session.commit()

    # ------------------------------------------------------------------
    # Summary CRUD
    # ------------------------------------------------------------------

    async def upsert_summary(
        self,
        session: AsyncSession,
        connection_id: str,
        summary_data: dict,
    ) -> DbIndexSummary:
        result = await session.execute(
            select(DbIndexSummary).where(DbIndexSummary.connection_id == connection_id)
        )
        entry = result.scalar_one_or_none()

        if entry:
            for key, value in summary_data.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.indexed_at = datetime.now(UTC)
            entry.updated_at = datetime.now(UTC)
        else:
            entry = DbIndexSummary(connection_id=connection_id, **summary_data)
            session.add(entry)

        await session.flush()
        return entry

    async def get_summary(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> DbIndexSummary | None:
        result = await session.execute(
            select(DbIndexSummary).where(DbIndexSummary.connection_id == connection_id)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    async def is_indexed(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> bool:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return False
        status = getattr(summary, "indexing_status", "idle") or "idle"
        if status == "running":
            return False
        return summary.indexed_at is not None

    async def get_index_age(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> timedelta | None:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return None
        return datetime.now(UTC) - summary.indexed_at.replace(tzinfo=UTC)

    async def is_stale(
        self,
        session: AsyncSession,
        connection_id: str,
        ttl_hours: int = 24,
    ) -> bool:
        """Return True if the index is older than *ttl_hours*."""
        age = await self.get_index_age(session, connection_id)
        if age is None:
            return False
        return age > timedelta(hours=ttl_hours)

    async def set_indexing_status(
        self,
        session: AsyncSession,
        connection_id: str,
        status: str,
    ) -> None:
        """Set indexing_status on DbIndexSummary (creates row if needed)."""
        summary = await self.get_summary(session, connection_id)
        if summary:
            summary.indexing_status = status
        else:
            summary = DbIndexSummary(
                connection_id=connection_id,
                indexing_status=status,
            )
            session.add(summary)
        await session.flush()

    async def get_indexing_status(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> str:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return "idle"
        return getattr(summary, "indexing_status", "idle") or "idle"

    async def get_status(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> dict:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return {"is_indexed": False}
        indexing_status = getattr(summary, "indexing_status", "idle") or "idle"
        actually_indexed = summary.indexed_at is not None and indexing_status != "running"
        return {
            "is_indexed": actually_indexed,
            "indexed_at": summary.indexed_at.isoformat() if summary.indexed_at else None,
            "total_tables": summary.total_tables,
            "active_tables": summary.active_tables,
            "empty_tables": summary.empty_tables,
            "orphan_tables": summary.orphan_tables,
            "phantom_tables": summary.phantom_tables,
            "indexing_status": indexing_status,
        }

    # ------------------------------------------------------------------
    # Compact table map for system prompt
    # ------------------------------------------------------------------

    @staticmethod
    def build_table_map(entries: list[DbIndex]) -> str:
        """One-liner-per-table map for injection into the system prompt.

        Only includes active tables with relevance >= 2 to keep it compact.
        Format: ``table_name(~rows, short description)``
        """
        items: list[str] = []
        for e in entries:
            if not e.is_active or e.relevance_score < 2:
                continue
            rows = f"~{e.row_count:,}" if e.row_count else "?"
            desc = (e.business_description or "")[:50].rstrip(".")
            items.append(f"{e.table_name}({rows}, {desc})")
        if not items:
            return ""
        return ", ".join(items)

    # ------------------------------------------------------------------
    # Formatting for LLM / query agent
    # ------------------------------------------------------------------

    @staticmethod
    def index_to_prompt_context(
        entries: list[DbIndex],
        summary: DbIndexSummary | None,
    ) -> str:
        if not entries:
            return ""

        parts: list[str] = []

        if summary and summary.indexed_at:
            parts.append(
                f"## Database Index (analyzed {summary.indexed_at.strftime('%Y-%m-%d %H:%M')})\n"
            )
        else:
            parts.append("## Database Index\n")

        high_rel = [e for e in entries if e.is_active and e.relevance_score >= 4]
        med_rel = [e for e in entries if e.is_active and 2 <= e.relevance_score < 4]
        low_active = [e for e in entries if e.is_active and e.relevance_score < 2]
        inactive = [e for e in entries if not e.is_active]

        if high_rel:
            parts.append("### Key Tables (high relevance)\n")
            parts.append("| Table | Rows | Description | Query Hints |")
            parts.append("|-------|------|-------------|-------------|")
            for e in high_rel:
                rows = f"~{e.row_count:,}" if e.row_count else "?"
                desc = (e.business_description or "")[:80]
                hints = (e.query_hints or "")[:80]
                parts.append(f"| {e.table_name} | {rows} | {desc} | {hints} |")
            parts.append("")

        if med_rel:
            parts.append("### Supporting Tables\n")
            parts.append("| Table | Rows | Description |")
            parts.append("|-------|------|-------------|")
            for e in med_rel:
                rows = f"~{e.row_count:,}" if e.row_count else "?"
                desc = (e.business_description or "")[:80]
                parts.append(f"| {e.table_name} | {rows} | {desc} |")
            parts.append("")

        omitted_count = len(inactive) + len(low_active)
        if omitted_count:
            parts.append(f"*({omitted_count} low-relevance/inactive tables omitted)*\n")

        if summary and summary.recommendations:
            parts.append("### Recommendations\n")
            parts.append(summary.recommendations)
            parts.append("")

        return "\n".join(parts)

    @staticmethod
    def table_index_to_detail(entry: DbIndex) -> str:
        parts: list[str] = [f"## {entry.table_name} — Index Analysis\n"]

        if entry.business_description:
            parts.append(f"**Description:** {entry.business_description}\n")
        parts.append(f"**Active:** {'Yes' if entry.is_active else 'No'}")
        parts.append(f"**Relevance:** {entry.relevance_score}/5")
        if entry.row_count is not None:
            parts.append(f"**Rows:** ~{entry.row_count:,}")
        if entry.code_match_status != "unknown":
            parts.append(f"**Code match:** {entry.code_match_status}")
            if entry.code_match_details:
                parts.append(f"  {entry.code_match_details}")

        if entry.data_patterns:
            parts.append(f"\n**Data patterns:** {entry.data_patterns}")

        if entry.query_hints:
            parts.append(f"\n**Query hints:** {entry.query_hints}")

        if entry.column_notes_json and entry.column_notes_json != "{}":
            try:
                notes = json.loads(entry.column_notes_json)
                if notes:
                    parts.append("\n**Column notes:**")
                    for col, note in notes.items():
                        parts.append(f"- `{col}`: {note}")
            except (json.JSONDecodeError, TypeError):
                pass

        numeric_notes_raw = getattr(entry, "numeric_format_notes", "{}")
        if numeric_notes_raw and numeric_notes_raw != "{}":
            try:
                numeric_notes = json.loads(numeric_notes_raw)
                if numeric_notes:
                    parts.append("\n**Numeric format notes:**")
                    for col, note in numeric_notes.items():
                        parts.append(f"- `{col}`: {note}")
            except (json.JSONDecodeError, TypeError):
                pass

        if entry.sample_data_json and entry.sample_data_json != "[]":
            try:
                samples = json.loads(entry.sample_data_json)
                if samples:
                    parts.append(f"\n**Sample data** ({len(samples)} newest rows):")
                    if isinstance(samples, list) and samples:
                        if isinstance(samples[0], dict):
                            cols = list(samples[0].keys())
                            parts.append("| " + " | ".join(cols) + " |")
                            parts.append("| " + " | ".join(["---"] * len(cols)) + " |")
                            for row in samples:
                                vals = [str(row.get(c, ""))[:40] for c in cols]
                                parts.append("| " + " | ".join(vals) + " |")
            except (json.JSONDecodeError, TypeError):
                pass

        return "\n".join(parts)

    @staticmethod
    def index_to_response(
        entries: list[DbIndex],
        summary: DbIndexSummary | None,
    ) -> dict:
        tables = []
        for e in entries:
            tables.append(
                {
                    "table_name": e.table_name,
                    "table_schema": e.table_schema,
                    "column_count": e.column_count,
                    "row_count": e.row_count,
                    "is_active": e.is_active,
                    "relevance_score": e.relevance_score,
                    "business_description": e.business_description,
                    "query_hints": e.query_hints,
                    "code_match_status": e.code_match_status,
                    "indexed_at": e.indexed_at.isoformat() if e.indexed_at else None,
                }
            )

        result: dict = {"tables": tables}
        if summary:
            result["summary"] = {
                "total_tables": summary.total_tables,
                "active_tables": summary.active_tables,
                "empty_tables": summary.empty_tables,
                "orphan_tables": summary.orphan_tables,
                "phantom_tables": summary.phantom_tables,
                "summary_text": summary.summary_text,
                "recommendations": summary.recommendations,
                "indexed_at": summary.indexed_at.isoformat() if summary.indexed_at else None,
            }
        return result
