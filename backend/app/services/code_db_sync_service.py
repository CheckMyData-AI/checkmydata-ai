"""CRUD and formatting for code-database synchronization entries."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update

from app.models.code_db_sync import CodeDbSync, CodeDbSyncSummary

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CodeDbSyncService:
    # ------------------------------------------------------------------
    # Per-table CRUD
    # ------------------------------------------------------------------

    async def upsert_table_sync(
        self,
        session: AsyncSession,
        connection_id: str,
        sync_data: dict,
    ) -> CodeDbSync:
        table_name = sync_data["table_name"]
        result = await session.execute(
            select(CodeDbSync).where(
                CodeDbSync.connection_id == connection_id,
                CodeDbSync.table_name == table_name,
            )
        )
        entry = result.scalar_one_or_none()

        if entry:
            for key, value in sync_data.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.synced_at = datetime.now(UTC)
            entry.updated_at = datetime.now(UTC)
        else:
            entry = CodeDbSync(connection_id=connection_id, **sync_data)
            session.add(entry)

        await session.flush()
        return entry

    async def get_sync(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> list[CodeDbSync]:
        result = await session.execute(
            select(CodeDbSync)
            .where(CodeDbSync.connection_id == connection_id)
            .order_by(CodeDbSync.confidence_score.desc(), CodeDbSync.table_name)
        )
        return list(result.scalars().all())

    async def get_table_sync(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
    ) -> CodeDbSync | None:
        result = await session.execute(
            select(CodeDbSync).where(
                CodeDbSync.connection_id == connection_id,
                CodeDbSync.table_name == table_name,
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
            select(CodeDbSync).where(CodeDbSync.connection_id == connection_id)
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
        await session.execute(delete(CodeDbSync).where(CodeDbSync.connection_id == connection_id))
        await session.execute(
            delete(CodeDbSyncSummary).where(CodeDbSyncSummary.connection_id == connection_id)
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
    ) -> CodeDbSyncSummary:
        result = await session.execute(
            select(CodeDbSyncSummary).where(CodeDbSyncSummary.connection_id == connection_id)
        )
        entry = result.scalar_one_or_none()

        if entry:
            for key, value in summary_data.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.synced_at = datetime.now(UTC)
            entry.updated_at = datetime.now(UTC)
        else:
            entry = CodeDbSyncSummary(connection_id=connection_id, **summary_data)
            session.add(entry)

        await session.flush()
        logger.info(
            "Sync summary saved: %s/%s tables for connection=%s",
            summary_data.get("synced_tables", "?"),
            summary_data.get("total_tables", "?"),
            connection_id[:8],
        )
        return entry

    async def get_summary(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> CodeDbSyncSummary | None:
        result = await session.execute(
            select(CodeDbSyncSummary).where(CodeDbSyncSummary.connection_id == connection_id)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    async def is_synced(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> bool:
        summary = await self.get_summary(session, connection_id)
        return summary is not None and summary.sync_status == "completed"

    async def set_sync_status(
        self,
        session: AsyncSession,
        connection_id: str,
        status: str,
    ) -> None:
        summary = await self.get_summary(session, connection_id)
        if summary:
            summary.sync_status = status
        else:
            summary = CodeDbSyncSummary(
                connection_id=connection_id,
                sync_status=status,
            )
            session.add(summary)
        await session.flush()
        logger.info(
            "Sync status → %s for connection=%s",
            status,
            connection_id[:8],
        )

    async def get_sync_status(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> str:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return "idle"
        return summary.sync_status or "idle"

    async def get_status(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> dict:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return {"is_synced": False}
        return {
            "is_synced": summary.sync_status == "completed",
            "synced_at": summary.synced_at.isoformat() if summary.synced_at else None,
            "total_tables": summary.total_tables,
            "synced_tables": summary.synced_tables,
            "code_only_tables": summary.code_only_tables,
            "db_only_tables": summary.db_only_tables,
            "mismatch_tables": summary.mismatch_tables,
            "sync_status": summary.sync_status or "idle",
            "is_syncing": summary.sync_status == "running",
        }

    async def mark_stale(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> None:
        """Mark sync as stale when underlying code or DB index changes."""
        summary = await self.get_summary(session, connection_id)
        if summary and summary.sync_status == "completed":
            summary.sync_status = "stale"
            await session.flush()

    async def mark_stale_for_project(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> None:
        """Mark all syncs stale for every connection in the project."""
        from app.models.connection import Connection

        result = await session.execute(
            select(Connection.id).where(Connection.project_id == project_id)
        )
        connection_ids = [r[0] for r in result.all()]

        if connection_ids:
            await session.execute(
                update(CodeDbSyncSummary)
                .where(
                    CodeDbSyncSummary.connection_id.in_(connection_ids),
                    CodeDbSyncSummary.sync_status == "completed",
                )
                .values(sync_status="stale")
            )
            await session.flush()

    # ------------------------------------------------------------------
    # Runtime enrichment (from investigation feedback loop)
    # ------------------------------------------------------------------

    async def add_runtime_enrichment(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
        field: str,
        value: str,
    ) -> CodeDbSync | None:
        """Patch a specific sync field without re-running the full pipeline.

        Supported fields: required_filters_json, column_value_mappings_json,
        query_recommendations, conversion_warnings.
        """
        entry = await self.get_table_sync(session, connection_id, table_name)
        if not entry:
            return None

        mergeable_json_fields = {"required_filters_json", "column_value_mappings_json"}
        appendable_text_fields = {"query_recommendations", "conversion_warnings"}

        if field in mergeable_json_fields:
            existing_json: dict[str, Any] = {}
            current_val = getattr(entry, field, None)
            if current_val:
                try:
                    existing_json = json.loads(current_val)
                except (json.JSONDecodeError, TypeError):
                    existing_json = {}
            try:
                new_data = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                new_data = {}
            if isinstance(existing_json, dict) and isinstance(new_data, dict):
                existing_json.update(new_data)
            setattr(entry, field, json.dumps(existing_json))
        elif field in appendable_text_fields:
            existing: str = getattr(entry, field, "") or ""
            if value not in existing:
                setattr(entry, field, f"{existing}\n{value}".strip())
        else:
            return None

        entry.updated_at = datetime.now(UTC)
        await session.flush()
        logger.info(
            "Runtime enrichment for %s.%s on connection=%s",
            table_name,
            field,
            connection_id[:8],
        )
        return entry

    # ------------------------------------------------------------------
    # Formatting for LLM / query agent
    # ------------------------------------------------------------------

    @staticmethod
    def sync_to_prompt_context(
        entries: list[CodeDbSync],
        summary: CodeDbSyncSummary | None,
    ) -> str:
        if not entries:
            return ""

        parts: list[str] = []

        if summary and summary.synced_at:
            parts.append(
                f"## Code-DB Sync (analyzed {summary.synced_at.strftime('%Y-%m-%d %H:%M')})\n"
            )
        else:
            parts.append("## Code-DB Sync\n")

        if summary and summary.global_notes:
            parts.append("### Project Data Overview\n")
            parts.append(summary.global_notes)
            parts.append("")

        if summary and summary.data_conventions:
            parts.append("### Project Data Conventions\n")
            parts.append(summary.data_conventions)
            parts.append("")

        warnings = [e for e in entries if e.conversion_warnings]
        if warnings:
            parts.append("### CRITICAL — Conversion Warnings\n")
            for e in warnings:
                parts.append(f"- **{e.table_name}**: {e.conversion_warnings}")
            parts.append("")

        matched = [e for e in entries if e.sync_status == "matched"]
        if matched:
            parts.append("### Synced Tables\n")
            parts.append("| Table | Data Format | Query Tips |")
            parts.append("|-------|-------------|------------|")
            for e in matched:
                fmt = (e.data_format_notes or "")[:80]
                tips = (e.query_recommendations or "")[:80]
                parts.append(f"| {e.table_name} | {fmt} | {tips} |")
            parts.append("")

        code_only_count = sum(1 for e in entries if e.sync_status == "code_only")
        db_only_count = sum(1 for e in entries if e.sync_status == "db_only")
        if code_only_count or db_only_count:
            omitted: list[str] = []
            if code_only_count:
                omitted.append(f"{code_only_count} code-only")
            if db_only_count:
                omitted.append(f"{db_only_count} DB-only")
            parts.append(f"*({', '.join(omitted)} tables omitted)*\n")

        if summary and summary.query_guidelines:
            parts.append("### Query Guidelines\n")
            parts.append(summary.query_guidelines)
            parts.append("")

        return "\n".join(parts)

    @staticmethod
    def table_sync_to_detail(entry: CodeDbSync) -> str:
        parts: list[str] = [f"## {entry.table_name} — Sync Analysis\n"]

        parts.append(f"**Status:** {entry.sync_status}")
        parts.append(f"**Confidence:** {entry.confidence_score}/5")

        if entry.entity_name:
            parts.append(f"**Code entity:** {entry.entity_name}")
        if entry.entity_file_path:
            parts.append(f"**Defined in:** `{entry.entity_file_path}`")

        parts.append(f"**Read by:** {entry.read_count} file(s)")
        parts.append(f"**Written by:** {entry.write_count} file(s)")

        if entry.conversion_warnings:
            parts.append(f"\n**WARNINGS:** {entry.conversion_warnings}")

        if entry.data_format_notes:
            parts.append(f"\n**Data formats:** {entry.data_format_notes}")

        if entry.business_logic_notes:
            parts.append(f"\n**Business logic:** {entry.business_logic_notes}")

        if entry.query_recommendations:
            parts.append(f"\n**Query tips:** {entry.query_recommendations}")

        if entry.column_sync_notes_json and entry.column_sync_notes_json != "{}":
            try:
                notes = json.loads(entry.column_sync_notes_json)
                if notes:
                    parts.append("\n**Column notes:**")
                    for col, note in notes.items():
                        parts.append(f"- `{col}`: {note}")
            except (json.JSONDecodeError, TypeError):
                pass

        if entry.used_in_files_json and entry.used_in_files_json != "[]":
            try:
                files = json.loads(entry.used_in_files_json)
                if files:
                    parts.append(f"\n**Used in:** {', '.join(f'`{f}`' for f in files[:10])}")
            except (json.JSONDecodeError, TypeError):
                pass

        return "\n".join(parts)

    @staticmethod
    def sync_to_response(
        entries: list[CodeDbSync],
        summary: CodeDbSyncSummary | None,
    ) -> dict:
        tables = []
        for e in entries:
            tables.append(
                {
                    "table_name": e.table_name,
                    "entity_name": e.entity_name,
                    "sync_status": e.sync_status,
                    "confidence_score": e.confidence_score,
                    "conversion_warnings": e.conversion_warnings,
                    "data_format_notes": e.data_format_notes,
                    "query_recommendations": e.query_recommendations,
                    "read_count": e.read_count,
                    "write_count": e.write_count,
                    "synced_at": e.synced_at.isoformat() if e.synced_at else None,
                }
            )

        result: dict = {"tables": tables}
        if summary:
            result["summary"] = {
                "total_tables": summary.total_tables,
                "synced_tables": summary.synced_tables,
                "code_only_tables": summary.code_only_tables,
                "db_only_tables": summary.db_only_tables,
                "mismatch_tables": summary.mismatch_tables,
                "global_notes": summary.global_notes,
                "data_conventions": summary.data_conventions,
                "query_guidelines": summary.query_guidelines,
                "synced_at": summary.synced_at.isoformat() if summary.synced_at else None,
            }
        return result
