"""Multi-pass indexing pipeline orchestrator.

Coordinates all knowledge extraction phases:
  Pass 1: Project profiling (detect framework, language, directories)
  Pass 2: Entity extraction (models, columns, FKs from each file)
  Pass 3: Cross-referencing (entity graph, usage map, enum resolution)
  Pass 4: LLM documentation with full cross-file context
  Pass 5: Chunking and vector storage
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.knowledge.entity_extractor import ProjectKnowledge, build_project_knowledge
from app.knowledge.file_splitter import split_large_file
from app.knowledge.project_profiler import ProjectProfile, detect_project_profile
from app.knowledge.project_summarizer import build_project_summary, build_schema_cross_reference
from app.knowledge.repo_analyzer import ExtractedSchema

logger = logging.getLogger(__name__)


@dataclass
class IndexingContext:
    """Carries state across pipeline passes."""

    repo_dir: Path
    project_id: str
    profile: ProjectProfile = field(default_factory=ProjectProfile)
    schemas: list[ExtractedSchema] = field(default_factory=list)
    knowledge: ProjectKnowledge = field(default_factory=ProjectKnowledge)
    all_source_files: list[str] = field(default_factory=list)


@dataclass
class EnrichedDoc:
    """A document ready for LLM doc generation, enriched with cross-file context."""

    file_path: str
    doc_type: str
    content: str
    models: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    enrichment_context: str = ""


def run_pass1_profile(repo_dir: Path) -> ProjectProfile:
    """Pass 1: Detect project type and directory structure."""
    logger.info("Indexing pass 1: detecting project profile for %s", repo_dir.name)
    return detect_project_profile(repo_dir)


def run_pass2_3_knowledge(
    repo_dir: Path,
    schemas: list[ExtractedSchema],
    all_files: list[str] | None = None,
    changed_files: list[str] | None = None,
    deleted_files: list[str] | None = None,
    cached_knowledge: ProjectKnowledge | None = None,
    detected_orms: list[str] | None = None,
) -> ProjectKnowledge:
    """Pass 2-3: Extract entities, build relationships, scan usage.

    When *cached_knowledge* and *changed_files* are both provided, only
    changed files are re-scanned (incremental mode).
    """
    logger.info(
        "Indexing pass 2-3: extracting entities (%d schemas, changed=%s)",
        len(schemas),
        len(changed_files) if changed_files else "all",
    )
    return build_project_knowledge(
        repo_dir,
        schemas,
        all_files,
        changed_files=changed_files,
        deleted_files=deleted_files,
        cached_knowledge=cached_knowledge,
        detected_orms=detected_orms,
    )


def run_pass4_enrich(
    schemas: list[ExtractedSchema],
    knowledge: ProjectKnowledge,
    profile: ProjectProfile | None = None,
) -> list[EnrichedDoc]:
    """Pass 4: Enrich each schema with cross-file context before doc generation.

    Also splits large files into per-class segments.
    """
    logger.info("Indexing pass 4: enriching %d schemas for doc generation", len(schemas))
    docs: list[EnrichedDoc] = []

    for schema in schemas:
        segments = split_large_file(schema.content, schema.file_path)

        for seg in segments:
            context_parts: list[str] = []

            if profile:
                context_parts.append(f"Project: {profile.summary}")

            for model_name in schema.models:
                entity = knowledge.entities.get(model_name)
                if not entity:
                    continue

                if entity.relationships:
                    context_parts.append(
                        f"Relationships for {model_name}: " + ", ".join(entity.relationships)
                    )

                for col in entity.columns:
                    if col.enum_values:
                        context_parts.append(
                            f"Column {col.name} allowed values: " + ", ".join(col.enum_values[:10])
                        )

                if entity.used_in_files:
                    context_parts.append(
                        f"{model_name} is used in: " + ", ".join(entity.used_in_files[:5])
                    )

            for tbl in schema.tables:
                usage = knowledge.table_usage.get(tbl)
                if usage and not usage.is_active:
                    context_parts.append(f"WARNING: Table '{tbl}' has no active references in code")

            related_services = [
                sf
                for sf in knowledge.service_functions
                if any(t in sf["tables"] for t in schema.tables)
                or any(m in sf.get("name", "") for m in schema.models)
            ]
            for sf in related_services[:3]:
                context_parts.append(
                    f"Service function {sf['name']} ({sf['file_path']}) "
                    f"operates on tables: {', '.join(sf['tables'])}"
                )

            enrichment = "\n".join(context_parts) if context_parts else ""

            docs.append(
                EnrichedDoc(
                    file_path=(
                        schema.file_path if len(segments) == 1 else f"{schema.file_path}#{seg.name}"
                    ),
                    doc_type=schema.doc_type,
                    content=seg.content,
                    models=schema.models,
                    tables=schema.tables,
                    enrichment_context=enrichment,
                )
            )

    return docs


def generate_summary_doc(
    knowledge: ProjectKnowledge,
    profile: ProjectProfile | None = None,
    live_table_names: list[str] | None = None,
) -> EnrichedDoc:
    """Create the project-level summary document.

    When *live_table_names* is provided (from a connected database),
    a schema cross-reference section is appended comparing code-discovered
    tables against the live DB.
    """
    summary_md = build_project_summary(knowledge, profile)
    if live_table_names:
        cross_ref = build_schema_cross_reference(knowledge, live_table_names)
        summary_md += "\n" + cross_ref
    return EnrichedDoc(
        file_path="__project_summary__",
        doc_type="project_summary",
        content=summary_md,
        models=[],
        tables=list(knowledge.table_usage.keys()),
    )
