"""Generate a unified project-level summary document from cross-file knowledge.

Pass 4 (partial): produces a single ``project_summary`` doc that lives
alongside per-file docs in the knowledge base.
"""

from __future__ import annotations

import logging

from app.knowledge.entity_extractor import ProjectKnowledge
from app.knowledge.project_profiler import ProjectProfile

logger = logging.getLogger(__name__)


def build_project_summary(
    knowledge: ProjectKnowledge,
    profile: ProjectProfile | None = None,
) -> str:
    """Return a markdown summary combining all cross-file knowledge."""
    sections: list[str] = []

    logger.debug("Generating project summary (%d entities)", len(knowledge.entities))
    sections.append("# Project Data Model Summary\n")

    if profile:
        sections.append(f"**Stack:** {profile.summary}\n")

    if knowledge.entities:
        sections.append("## Entities\n")
        for name, entity in sorted(knowledge.entities.items()):
            line = f"### {name}"
            if entity.table_name:
                line += f" (`{entity.table_name}`)"
            sections.append(line)
            if entity.file_path:
                sections.append(f"Defined in: `{entity.file_path}`")
            if entity.columns:
                sections.append("| Column | Type | FK | Enum Values |")
                sections.append("|--------|------|----|-------------|")
                for col in entity.columns:
                    fk = col.fk_target if col.is_fk else ""
                    enums = ", ".join(col.enum_values[:8]) if col.enum_values else ""
                    sections.append(f"| {col.name} | {col.col_type} | {fk} | {enums} |")
            if entity.relationships:
                sections.append("**Relationships:** " + ", ".join(entity.relationships))
            if entity.used_in_files:
                sections.append(
                    f"**Used in:** {len(entity.used_in_files)} file(s) — "
                    + ", ".join(f"`{f}`" for f in entity.used_in_files[:5])
                )
            sections.append("")

    if knowledge.table_usage:
        sections.append("## Table Usage Map\n")
        sections.append("| Table | Readers | Writers | ORM Refs | Status |")
        sections.append("|-------|---------|---------|----------|--------|")
        for tbl_name, usage in sorted(knowledge.table_usage.items()):
            status = "active" if usage.is_active else "UNUSED"
            sections.append(
                f"| {tbl_name} "
                f"| {len(usage.readers)} "
                f"| {len(usage.writers)} "
                f"| {len(usage.orm_refs)} "
                f"| {status} |"
            )
        sections.append("")

    dead = knowledge.dead_tables
    if dead:
        sections.append("## Potentially Dead Tables\n")
        sections.append(
            "These tables appear in schema/migrations but have "
            "**zero** references in application code:\n"
        )
        for t in dead:
            sections.append(f"- `{t}`")
        sections.append("")

    if knowledge.enums:
        total_enums = len(knowledge.enums)
        shown = min(total_enums, 50)
        sections.append(f"## Enum / Constant Definitions ({shown}/{total_enums})\n")
        for enum_def in knowledge.enums[:shown]:
            vals = ", ".join(enum_def.values[:12])
            if len(enum_def.values) > 12:
                vals += f" (+{len(enum_def.values) - 12} more)"
            sections.append(f"- **{enum_def.name}** (`{enum_def.file_path}`): {vals}")
        if total_enums > shown:
            sections.append(
                f"\n*{total_enums - shown} more enum(s) omitted. "
                "Use `get_entity_info(scope='enums')` to see all.*"
            )
        sections.append("")

    if knowledge.service_functions:
        total_sf = len(knowledge.service_functions)
        shown = min(total_sf, 50)
        sections.append(f"## Key Service Functions ({shown}/{total_sf})\n")
        for sf in knowledge.service_functions[:shown]:
            tables = ", ".join(sf.get("tables") or [])
            sections.append(f"- `{sf['name']}` in `{sf['file_path']}` → tables: {tables}")
        if total_sf > shown:
            sections.append(
                f"\n*{total_sf - shown} more function(s) omitted. "
                "Use `get_entity_info(scope='enums')` to see all.*"
            )
        sections.append("")

    if knowledge.config_refs:
        unique_vars = {}
        for cref in knowledge.config_refs:
            if cref.var_name not in unique_vars:
                unique_vars[cref.var_name] = cref
        sections.append("## Database Configuration References\n")
        for var_name, cref in sorted(unique_vars.items()):
            sections.append(f"- `{var_name}` in `{cref.file_path}`")
        sections.append("")

    return "\n".join(sections)


def build_schema_cross_reference(
    knowledge: ProjectKnowledge,
    live_table_names: list[str],
) -> str:
    """Compare code-discovered tables against live DB tables.

    Returns markdown describing orphan and phantom tables.
    """
    code_tables = set()
    for entity in knowledge.entities.values():
        if entity.table_name:
            code_tables.add(entity.table_name.lower())
    for tbl in knowledge.table_usage:
        code_tables.add(tbl.lower())

    db_tables = {t.lower() for t in live_table_names}

    orphans = db_tables - code_tables
    phantoms = code_tables - db_tables

    lines = ["## Schema Cross-Reference\n"]

    if orphans:
        lines.append("### Orphan Tables (in DB, not in code)")
        lines.append("These tables exist in the database but have no references in the codebase:\n")
        for t in sorted(orphans):
            lines.append(f"- `{t}`")
        lines.append("")

    if phantoms:
        lines.append("### Phantom Tables (in code, not in DB)")
        lines.append(
            "These tables are referenced in code but were not found in the live database "
            "(may be from a different environment or pending migration):\n"
        )
        for t in sorted(phantoms):
            lines.append(f"- `{t}`")
        lines.append("")

    if not orphans and not phantoms:
        lines.append("All tables in the database match references in the codebase.\n")

    return "\n".join(lines)
