"""Generates a unified Project Knowledge Overview for the orchestrator agent.

Supports incremental updates: each section is hashed and only rebuilt
when the underlying data changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.agent_learning import AgentLearning
from app.models.code_db_sync import CodeDbSync, CodeDbSyncSummary
from app.models.connection import Connection
from app.models.custom_rule import CustomRule
from app.models.db_index import DbIndex, DbIndexSummary
from app.models.project_cache import ProjectCache
from app.models.session_note import SessionNote

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_KEY_TABLES = 10
MAX_TOP_LEARNINGS = 5
MAX_BENCHMARKS = 10
MAX_OVERVIEW_CHARS = 6000

SECTION_KEYS = (
    "db",
    "sync",
    "rules",
    "learnings",
    "notes",
    "profile",
)


def _hash_section(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class ProjectOverviewService:
    """Builds a compact markdown overview combining all knowledge sources."""

    async def generate_overview(
        self,
        db: AsyncSession,
        project_id: str,
        connection_id: str | None = None,
    ) -> str:
        sections: list[str] = []

        connection_ids = await self._get_connection_ids(
            db,
            project_id,
            connection_id,
        )
        if not connection_ids:
            return ""

        db_section = await self._build_db_section(db, connection_ids)
        if db_section:
            sections.append(db_section)

        sync_section = await self._build_sync_section(db, connection_ids)
        if sync_section:
            sections.append(sync_section)

        rules_section = await self._build_rules_section(db, project_id)
        if rules_section:
            sections.append(rules_section)

        learnings_section = await self._build_learnings_section(
            db,
            connection_ids,
        )
        if learnings_section:
            sections.append(learnings_section)

        notes_section = await self._build_notes_section(
            db,
            project_id,
            connection_ids,
        )
        if notes_section:
            sections.append(notes_section)

        profile_section = await self._build_profile_section(
            db,
            project_id,
        )
        if profile_section:
            sections.append(profile_section)

        overview = "\n\n".join(sections)
        if len(overview) > MAX_OVERVIEW_CHARS:
            overview = overview[:MAX_OVERVIEW_CHARS] + "\n...(truncated)"
        return overview

    async def save_overview(
        self,
        db: AsyncSession,
        project_id: str,
        connection_id: str | None = None,
    ) -> str:
        row = await db.execute(select(ProjectCache).where(ProjectCache.project_id == project_id))
        cache = row.scalar_one_or_none()

        old_hashes: dict[str, str] = {}
        if cache:
            try:
                old_hashes = json.loads(cache.section_hashes_json or "{}")
            except (json.JSONDecodeError, TypeError):
                old_hashes = {}

        connection_ids = await self._get_connection_ids(
            db,
            project_id,
            connection_id,
        )
        if not connection_ids:
            if cache:
                cache.overview_text = ""
                cache.overview_generated_at = datetime.now(UTC)
                cache.section_hashes_json = "{}"
            await db.commit()
            return ""

        builders = {
            "db": lambda: self._build_db_section(db, connection_ids),
            "sync": lambda: self._build_sync_section(db, connection_ids),
            "rules": lambda: self._build_rules_section(db, project_id),
            "learnings": lambda: self._build_learnings_section(
                db,
                connection_ids,
            ),
            "notes": lambda: self._build_notes_section(
                db,
                project_id,
                connection_ids,
            ),
            "profile": lambda: self._build_profile_section(db, project_id),
        }

        old_overview = (cache.overview_text or "") if cache else ""
        old_sections = self._split_overview_sections(old_overview)

        new_hashes: dict[str, str] = {}
        final_sections: list[str] = []
        regenerated_count = 0

        for key in SECTION_KEYS:
            builder = builders[key]
            new_text = await builder()
            if not new_text:
                continue

            new_hash = _hash_section(new_text)
            new_hashes[key] = new_hash

            if new_hash == old_hashes.get(key) and key in old_sections:
                final_sections.append(old_sections[key])
            else:
                final_sections.append(new_text)
                regenerated_count += 1

        overview = "\n\n".join(final_sections)
        if len(overview) > MAX_OVERVIEW_CHARS:
            overview = overview[:MAX_OVERVIEW_CHARS] + "\n...(truncated)"

        if cache:
            cache.overview_text = overview
            cache.overview_generated_at = datetime.now(UTC)
            cache.section_hashes_json = json.dumps(new_hashes)
        else:
            cache = ProjectCache(
                project_id=project_id,
                overview_text=overview,
                overview_generated_at=datetime.now(UTC),
                section_hashes_json=json.dumps(new_hashes),
            )
            db.add(cache)

        await db.commit()

        if regenerated_count < len(final_sections):
            logger.info(
                "Incremental overview: %d/%d sections regenerated",
                regenerated_count,
                len(final_sections),
            )

        return overview

    @staticmethod
    def _split_overview_sections(overview: str) -> dict[str, str]:
        """Parse a previously generated overview back into section map."""
        sections: dict[str, str] = {}
        header_map = {
            "## Database Structure": "db",
            "## Data Conventions": "sync",
            "## Custom Rules": "rules",
            "## Agent Learnings": "learnings",
            "## Session Notes": "notes",
            "## Repository Profile": "profile",
        }
        current_key: str | None = None
        current_lines: list[str] = []

        for line in overview.split("\n"):
            matched = False
            for header, key in header_map.items():
                if line.startswith(header):
                    if current_key and current_lines:
                        sections[current_key] = "\n".join(current_lines)
                    current_key = key
                    current_lines = [line]
                    matched = True
                    break
            if not matched and current_key is not None:
                current_lines.append(line)

        if current_key and current_lines:
            sections[current_key] = "\n".join(current_lines)

        return sections

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_connection_ids(
        self,
        db: AsyncSession,
        project_id: str,
        connection_id: str | None,
    ) -> list[str]:
        if connection_id:
            return [connection_id]
        result = await db.execute(select(Connection.id).where(Connection.project_id == project_id))
        return list(result.scalars().all())

    async def _build_db_section(self, db: AsyncSession, connection_ids: list[str]) -> str:
        if not connection_ids:
            return ""
        parts: list[str] = ["## Database Structure"]

        summary_rows = await db.execute(
            select(DbIndexSummary).where(DbIndexSummary.connection_id.in_(connection_ids))
        )
        for summary in summary_rows.scalars().all():
            parts.append(
                f"Tables: {summary.total_tables} total, "
                f"{summary.active_tables} active, "
                f"{summary.empty_tables} empty"
            )

        idx_rows = await db.execute(
            select(DbIndex)
            .where(
                DbIndex.connection_id.in_(connection_ids),
                DbIndex.is_active.is_(True),
            )
            .order_by(DbIndex.relevance_score.desc(), DbIndex.row_count.desc())
            .limit(MAX_KEY_TABLES * len(connection_ids))
        )
        tables = list(idx_rows.scalars().all())

        for tbl in tables:
            row_str = f"~{tbl.row_count:,}" if tbl.row_count else "?"
            line = f"- **{tbl.table_name}** ({row_str} rows, rel={tbl.relevance_score})"
            if tbl.business_description:
                desc = tbl.business_description[:100]
                line += f": {desc}"
            parts.append(line)

            distinct_raw = tbl.column_distinct_values_json or "{}"
            try:
                distinct = json.loads(distinct_raw)
                for col, vals in list(distinct.items())[:5]:
                    display = ", ".join(str(v) for v in vals[:8])
                    parts.append(f"  - `{col}`: [{display}]")
            except (json.JSONDecodeError, TypeError):
                pass

        return "\n".join(parts) if len(parts) > 1 else ""

    async def _build_sync_section(self, db: AsyncSession, connection_ids: list[str]) -> str:
        if not connection_ids:
            return ""
        parts: list[str] = ["## Data Conventions (Code-DB Sync)"]
        has_content = False

        sum_rows = await db.execute(
            select(CodeDbSyncSummary).where(CodeDbSyncSummary.connection_id.in_(connection_ids))
        )
        for summary in sum_rows.scalars().all():
            if summary.data_conventions:
                parts.append(f"**Conventions:** {summary.data_conventions[:300]}")
                has_content = True
            if summary.query_guidelines:
                parts.append(f"**Query guidelines:** {summary.query_guidelines[:300]}")
                has_content = True

        sync_rows = await db.execute(
            select(CodeDbSync)
            .where(CodeDbSync.connection_id.in_(connection_ids))
            .order_by(CodeDbSync.confidence_score.desc())
        )
        syncs = list(sync_rows.scalars().all())

        filters_found = False
        mappings_found = False
        for s in syncs:
            rf = s.required_filters_json or "{}"
            try:
                filters = json.loads(rf)
                if filters:
                    if not filters_found:
                        parts.append("**Required filters:**")
                        filters_found = True
                        has_content = True
                    for col, filt in filters.items():
                        parts.append(f"- `{s.table_name}.{col}`: {filt}")
            except (json.JSONDecodeError, TypeError):
                pass

            vm = s.column_value_mappings_json or "{}"
            try:
                mappings = json.loads(vm)
                if mappings:
                    if not mappings_found:
                        parts.append("**Column value mappings:**")
                        mappings_found = True
                        has_content = True
                    for col, mapping in mappings.items():
                        parts.append(f"- `{s.table_name}.{col}`: {mapping}")
            except (json.JSONDecodeError, TypeError):
                pass

            if s.conversion_warnings:
                parts.append(f"- **Warning** ({s.table_name}): {s.conversion_warnings[:150]}")
                has_content = True

        return "\n".join(parts) if has_content else ""

    async def _build_rules_section(self, db: AsyncSession, project_id: str) -> str:
        result = await db.execute(
            select(CustomRule)
            .where((CustomRule.project_id == project_id) | (CustomRule.project_id.is_(None)))
            .order_by(CustomRule.created_at.desc())
        )
        rules = list(result.scalars().all())
        if not rules:
            return ""

        parts: list[str] = [f"## Custom Rules ({len(rules)})"]
        for rule in rules:
            first_line = (rule.content or "").split("\n", 1)[0][:120]
            parts.append(f"- **{rule.name}**: {first_line}")
        return "\n".join(parts)

    async def _build_learnings_section(self, db: AsyncSession, connection_ids: list[str]) -> str:
        if not connection_ids:
            return ""

        count_result = await db.execute(
            select(AgentLearning.category, func.count(AgentLearning.id))
            .where(
                AgentLearning.connection_id.in_(connection_ids),
                AgentLearning.is_active.is_(True),
            )
            .group_by(AgentLearning.category)
        )
        counts: dict[str, int] = {str(r[0]): int(r[1]) for r in count_result.all()}
        if not counts:
            return ""

        parts: list[str] = ["## Agent Learnings"]
        total = sum(counts.values())
        cat_summary = ", ".join(f"{cat}: {cnt}" for cat, cnt in counts.items())
        parts.append(f"Total: {total} active ({cat_summary})")

        top_result = await db.execute(
            select(AgentLearning)
            .where(
                AgentLearning.connection_id.in_(connection_ids),
                AgentLearning.is_active.is_(True),
            )
            .order_by(AgentLearning.confidence.desc(), AgentLearning.times_confirmed.desc())
            .limit(MAX_TOP_LEARNINGS)
        )
        top = list(top_result.scalars().all())
        for learn in top:
            lesson_short = (learn.lesson or "")[:120]
            parts.append(f"- [{learn.category}] {lesson_short} (conf={learn.confidence:.1f})")

        return "\n".join(parts)

    async def _build_notes_section(
        self,
        db: AsyncSession,
        project_id: str,
        connection_ids: list[str],
    ) -> str:
        note_result = await db.execute(
            select(SessionNote.category, func.count(SessionNote.id))
            .where(
                SessionNote.project_id == project_id,
                SessionNote.is_active.is_(True),
            )
            .group_by(SessionNote.category)
        )
        note_counts: dict[str, int] = {str(r[0]): int(r[1]) for r in note_result.all()}

        from app.models.benchmark import DataBenchmark

        bench_result = await db.execute(
            select(DataBenchmark)
            .where(DataBenchmark.connection_id.in_(connection_ids))
            .order_by(DataBenchmark.times_confirmed.desc())
            .limit(MAX_BENCHMARKS)
        )
        benchmarks = list(bench_result.scalars().all())

        if not note_counts and not benchmarks:
            return ""

        parts: list[str] = ["## Session Notes & Benchmarks"]
        if note_counts:
            cat_summary = ", ".join(f"{cat}: {cnt}" for cat, cnt in note_counts.items())
            parts.append(f"Notes: {cat_summary}")
        if benchmarks:
            parts.append("Verified benchmarks:")
            for b in benchmarks:
                unit = f" {b.unit}" if b.unit else ""
                parts.append(f"- {b.metric_key}: {b.value}{unit} (x{b.times_confirmed} confirmed)")

        return "\n".join(parts)

    async def _build_profile_section(self, db: AsyncSession, project_id: str) -> str:
        row = await db.execute(select(ProjectCache).where(ProjectCache.project_id == project_id))
        cache = row.scalar_one_or_none()
        if not cache or cache.profile_json in ("{}", "", None):
            return ""

        try:
            profile = json.loads(cache.profile_json)
        except (json.JSONDecodeError, TypeError):
            return ""

        parts: list[str] = ["## Repository Profile"]

        lang = profile.get("primary_language", "")
        frameworks = profile.get("frameworks", [])
        orms = profile.get("orms", [])
        if lang:
            stack_parts = [lang]
            if frameworks:
                stack_parts.append(", ".join(frameworks[:5]))
            if orms:
                stack_parts.append(f"ORM: {', '.join(orms[:3])}")
            parts.append(f"Stack: {' | '.join(stack_parts)}")

        key_dirs = profile.get("key_directories", {})
        if key_dirs:
            dir_items = [f"{k}: {v}" for k, v in list(key_dirs.items())[:5]]
            parts.append(f"Key dirs: {', '.join(dir_items)}")

        return "\n".join(parts) if len(parts) > 1 else ""
