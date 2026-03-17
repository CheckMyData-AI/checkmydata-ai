"""Resumable indexing pipeline runner.

Wraps the multi-pass indexing logic with checkpoint-based state tracking
so that interrupted runs can be resumed from the last completed step.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from git import Repo

from app.core.workflow_tracker import tracker
from app.knowledge.chunker import chunk_document
from app.knowledge.indexing_pipeline import (
    generate_summary_doc,
    run_pass1_profile,
    run_pass2_3_knowledge,
    run_pass4_enrich,
)
from app.services.checkpoint_service import CheckpointService

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.knowledge.doc_generator import DocGenerator
    from app.knowledge.doc_store import DocStore
    from app.knowledge.entity_extractor import ProjectKnowledge
    from app.knowledge.git_tracker import GitTracker
    from app.knowledge.indexing_pipeline import EnrichedDoc
    from app.knowledge.project_profiler import ProjectProfile
    from app.knowledge.repo_analyzer import RepoAnalyzer
    from app.knowledge.vector_store import VectorStore
    from app.models.indexing_checkpoint import IndexingCheckpoint
    from app.services.project_cache_service import ProjectCacheService
    from app.services.ssh_key_service import SshKeyService

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    status: str = "completed"
    commit_sha: str = ""
    files_indexed: int = 0
    schemas_found: int = 0
    resumed: bool = False
    resumed_from_step: str | None = None
    docs_skipped: int = 0


@dataclass
class _PipelineState:
    """Mutable state carried between pipeline steps."""

    ssh_key_content: str | None = None
    ssh_key_passphrase: str | None = None
    repo_dir: Path | None = None
    head_sha: str = ""
    last_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    profile: ProjectProfile | None = None
    schemas: list = field(default_factory=list)
    knowledge: ProjectKnowledge | None = None
    enriched_docs: list[EnrichedDoc] = field(default_factory=list)


class IndexingPipelineRunner:
    def __init__(
        self,
        ssh_key_svc: SshKeyService,
        git_tracker: GitTracker,
        repo_analyzer: RepoAnalyzer,
        doc_store: DocStore,
        doc_generator: DocGenerator,
        vector_store: VectorStore,
        cache_svc: ProjectCacheService,
        checkpoint_svc: CheckpointService,
    ) -> None:
        self._ssh_key_svc = ssh_key_svc
        self._git_tracker = git_tracker
        self._repo_analyzer = repo_analyzer
        self._doc_store = doc_store
        self._doc_generator = doc_generator
        self._vector_store = vector_store
        self._cache_svc = cache_svc
        self._cp_svc = checkpoint_svc

    async def run(
        self,
        project_id: str,
        project,
        force_full: bool,
        db: AsyncSession,
        wf_id: str,
        checkpoint: IndexingCheckpoint,
    ) -> PipelineResult:
        cp_id = checkpoint.id
        done = CheckpointService.get_completed_steps(checkpoint)
        resuming = len(done) > 0
        result = PipelineResult(resumed=resuming)
        state = _PipelineState()

        if resuming:
            result.resumed_from_step = sorted(done)[-1] if done else None
            await tracker.emit(
                wf_id,
                "pipeline_resume",
                "started",
                f"Resuming from checkpoint ({len(done)} steps done, "
                f"{len(CheckpointService.get_processed_doc_paths(checkpoint))} docs processed)",
            )

        # --- Step 1: resolve_ssh_key (always re-run, fast) ---
        async with tracker.step(wf_id, "resolve_ssh_key", "Decrypting SSH key"):
            if project.ssh_key_id:
                decrypted = await self._ssh_key_svc.get_decrypted(db, project.ssh_key_id)
                if decrypted:
                    state.ssh_key_content, state.ssh_key_passphrase = decrypted

        # --- Step 2: clone_or_pull (always re-run, pull is fast) ---
        async with tracker.step(
            wf_id,
            "clone_or_pull",
            f"Cloning/pulling {project.repo_url}",
        ):
            state.repo_dir = await asyncio.to_thread(
                self._repo_analyzer.clone_or_pull,
                repo_url=project.repo_url,
                project_id=project_id,
                branch=project.repo_branch,
                ssh_key_content=state.ssh_key_content,
                ssh_key_passphrase=state.ssh_key_passphrase,
            )

        # --- Step 3: detect_changes ---
        if "detect_changes" in done:
            state.head_sha = checkpoint.head_sha
            state.last_sha = checkpoint.last_sha
            state.changed_files = CheckpointService.get_changed_files(checkpoint)
            state.deleted_files = CheckpointService.get_deleted_files(checkpoint)
            await tracker.emit(
                wf_id,
                "detect_changes",
                "skipped",
                f"Restored from checkpoint: {len(state.changed_files)} changed, "
                f"{len(state.deleted_files)} deleted",
            )
        else:
            async with tracker.step(wf_id, "detect_changes", "Computing changed files"):
                state.head_sha = await asyncio.to_thread(
                    self._git_tracker.get_head_sha,
                    state.repo_dir,
                )
                if force_full:
                    state.last_sha = None
                else:
                    state.last_sha = await self._git_tracker.get_last_indexed_sha(
                        db,
                        project_id,
                        branch=project.repo_branch,
                    )
                diff = await asyncio.to_thread(
                    self._git_tracker.get_changed_files,
                    state.repo_dir,
                    state.last_sha,
                    state.head_sha,
                )
                state.changed_files = diff.changed
                state.deleted_files = diff.deleted
            await tracker.emit(
                wf_id,
                "detect_changes",
                "completed",
                f"{len(state.changed_files)} changed, {len(state.deleted_files)} deleted",
            )
            await self._cp_svc.complete_step(
                db,
                cp_id,
                "detect_changes",
                head_sha=state.head_sha,
                last_sha=state.last_sha,
                changed_files=state.changed_files,
                deleted_files=state.deleted_files,
            )

        # --- Step 4: cleanup_deleted ---
        if "cleanup_deleted" not in done:
            if state.deleted_files:
                async with tracker.step(
                    wf_id,
                    "cleanup_deleted",
                    f"Removing {len(state.deleted_files)} deleted file(s) from knowledge base",
                ):
                    await self._doc_store.delete_docs_for_paths(
                        db,
                        project_id,
                        state.deleted_files,
                    )
                    for dpath in state.deleted_files:
                        await asyncio.to_thread(
                            self._vector_store.delete_by_source_path,
                            project_id,
                            dpath,
                        )
            await self._cp_svc.complete_step(db, cp_id, "cleanup_deleted")

        # --- Step 5: project_profile ---
        if "project_profile" in done and checkpoint.profile_json != "{}":
            from app.knowledge.project_profiler import ProjectProfile as PProf

            try:
                state.profile = PProf.from_json(checkpoint.profile_json)
            except Exception:
                state.profile = None
            if state.profile:
                await tracker.emit(
                    wf_id,
                    "project_profile",
                    "skipped",
                    f"Restored from checkpoint: {state.profile.summary}",
                )

        if state.profile is None:
            async with tracker.step(
                wf_id,
                "project_profile",
                "Detecting project framework and structure",
            ):
                cached_profile = await self._cache_svc.load_profile(db, project_id)
                marker_overlap = False
                if cached_profile and not force_full:
                    marker_overlap = bool(
                        cached_profile.marker_files & set(state.changed_files),
                    )
                if cached_profile and not force_full and not marker_overlap:
                    state.profile = cached_profile
                else:
                    state.profile = await asyncio.to_thread(run_pass1_profile, state.repo_dir)
            await tracker.emit(
                wf_id,
                "project_profile",
                "completed",
                state.profile.summary,
            )
            await self._cp_svc.complete_step(
                db,
                cp_id,
                "project_profile",
                profile_json=state.profile.to_json(),
            )

        # --- Step 6: analyze_files (always re-run; ~60s but deterministic) ---
        async with tracker.step(
            wf_id,
            "analyze_files",
            f"Analyzing {len(state.changed_files)} files",
        ):
            raw_schemas = await asyncio.to_thread(
                self._repo_analyzer.analyze,
                state.repo_dir,
                state.changed_files,
                state.profile,
            )
            merged: dict[str, Any] = {}
            for s in raw_schemas:
                key = s.file_path
                if key in merged:
                    existing = merged[key]
                    existing.doc_type = (
                        s.doc_type if s.doc_type == "orm_model" else existing.doc_type
                    )
                    existing.models = list(dict.fromkeys(existing.models + s.models))
                    existing.tables = list(dict.fromkeys(existing.tables + s.tables))
                    if s.doc_type == "query_pattern" and s.content not in existing.content:
                        existing.content += f"\n\n---\n\n{s.content}"
                else:
                    merged[key] = s
            state.schemas = list(merged.values())

        # --- Step 7: cross_file_analysis ---
        if "cross_file_analysis" in done and checkpoint.knowledge_json != "{}":
            from app.knowledge.entity_extractor import ProjectKnowledge as PKnow

            try:
                state.knowledge = PKnow.from_json(checkpoint.knowledge_json)
            except Exception:
                state.knowledge = None
            if state.knowledge:
                await tracker.emit(
                    wf_id,
                    "cross_file_analysis",
                    "skipped",
                    f"Restored from checkpoint: {len(state.knowledge.entities)} entities",
                )

        if state.knowledge is None:
            async with tracker.step(
                wf_id,
                "cross_file_analysis",
                "Building entity map, usage tracking, and enum extraction",
            ):
                cached_knowledge = None
                if not force_full:
                    cached_knowledge = await self._cache_svc.load_knowledge(db, project_id)
                is_incremental = cached_knowledge is not None and state.last_sha is not None
                state.knowledge = await asyncio.to_thread(
                    run_pass2_3_knowledge,
                    state.repo_dir,
                    state.schemas,
                    changed_files=state.changed_files if is_incremental else None,
                    deleted_files=state.deleted_files if is_incremental else None,
                    cached_knowledge=cached_knowledge,
                )
            await tracker.emit(
                wf_id,
                "cross_file_analysis",
                "completed",
                f"{len(state.knowledge.entities)} entities, "
                f"{len(state.knowledge.dead_tables)} dead tables, "
                f"{len(state.knowledge.enums)} enums"
                + (
                    " (incremental)"
                    if (cached_knowledge is not None and state.last_sha is not None)
                    else " (full)"
                ),
            )
            await self._cp_svc.complete_step(
                db,
                cp_id,
                "cross_file_analysis",
                knowledge_json=state.knowledge.to_json(),
            )

        # --- Step 8: enrich + summary (always re-run; fast, in-memory) ---
        state.enriched_docs = await asyncio.to_thread(
            run_pass4_enrich,
            state.schemas,
            state.knowledge,
            state.profile,
        )
        summary_doc = generate_summary_doc(state.knowledge, state.profile)
        state.enriched_docs.append(summary_doc)

        existing_summary = await self._doc_store.get_docs_for_project(
            db,
            project_id,
            doc_type="project_summary",
        )
        existing_summary_hash = ""
        if existing_summary:
            existing_summary_hash = hashlib.md5(
                existing_summary[0].content.encode(),
            ).hexdigest()

        # --- Step 9: generate_docs (per-doc atomic with checkpoint) ---
        processed_paths = CheckpointService.get_processed_doc_paths(checkpoint)
        total = len(state.enriched_docs)
        skipped = 0
        batch_flush_size = 10

        await self._cp_svc.complete_step(db, cp_id, "enrich_docs", total_docs=total)

        async with tracker.step(
            wf_id,
            "generate_docs",
            f"Generating docs for {total} items"
            + (f" ({len(processed_paths)} already done)" if processed_paths else ""),
        ):
            pending_paths: list[str] = []

            for i, edoc in enumerate(state.enriched_docs):
                if edoc.file_path in processed_paths:
                    skipped += 1
                    continue

                await tracker.emit(
                    wf_id,
                    "generate_docs",
                    "started",
                    f"Processing {edoc.file_path} ({i + 1}/{total})",
                )

                if edoc.file_path == "__project_summary__":
                    new_hash = hashlib.md5(edoc.content.encode()).hexdigest()
                    if new_hash == existing_summary_hash:
                        logger.info("Project summary unchanged, skipping LLM call")
                        pending_paths.append(edoc.file_path)
                        if len(pending_paths) >= batch_flush_size:
                            await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                            pending_paths = []
                        continue

                generated_content = await self._doc_generator.generate(
                    file_path=edoc.file_path,
                    content=edoc.content,
                    doc_type=edoc.doc_type,
                    preferred_provider=project.default_llm_provider,
                    model=project.default_llm_model,
                    enrichment_context=edoc.enrichment_context,
                )

                doc = await self._doc_store.upsert(
                    session=db,
                    project_id=project_id,
                    doc_type=edoc.doc_type,
                    source_path=edoc.file_path,
                    content=generated_content,
                    commit_sha=state.head_sha,
                )

                await asyncio.to_thread(
                    self._vector_store.delete_by_source_path,
                    project_id,
                    edoc.file_path,
                )

                chunks = chunk_document(
                    content=generated_content,
                    file_path=edoc.file_path,
                    doc_type=edoc.doc_type,
                    extra_metadata={
                        "commit_sha": state.head_sha,
                        "models": ",".join(edoc.models),
                        "tables": ",".join(edoc.tables),
                    },
                )
                if chunks:
                    chunk_ids = [f"{doc.id}:{c.metadata.get('chunk_index', '0')}" for c in chunks]
                    chunk_docs = [c.content for c in chunks]
                    chunk_metas = [c.metadata for c in chunks]
                    await asyncio.to_thread(
                        self._vector_store.add_documents,
                        project_id=project_id,
                        doc_ids=chunk_ids,
                        documents=chunk_docs,
                        metadatas=chunk_metas,
                    )

                pending_paths.append(edoc.file_path)
                if len(pending_paths) >= batch_flush_size:
                    await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                    pending_paths = []

            if pending_paths:
                await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)

        result.docs_skipped = skipped

        # --- Step 10: record_index ---
        async with tracker.step(wf_id, "record_index", "Recording commit index"):
            repo = await asyncio.to_thread(Repo, str(state.repo_dir))
            commit_msg = repo.head.commit.message.strip()[:200]
            await self._git_tracker.record_index(
                session=db,
                project_id=project_id,
                commit_sha=state.head_sha,
                commit_message=commit_msg,
                indexed_files=state.changed_files,
                branch=project.repo_branch,
            )
            await self._git_tracker.cleanup_old_records(db, project_id, keep=10)
            await self._cache_svc.save(
                db,
                project_id,
                knowledge=state.knowledge,
                profile=state.profile,
            )

        # --- Cleanup checkpoint ---
        await self._cp_svc.delete(db, cp_id)

        await tracker.end(
            wf_id,
            "index_repo",
            "completed",
            f"Indexed {len(state.changed_files)} files, {len(state.schemas)} schemas"
            + (f" (resumed, {skipped} docs skipped)" if resuming else ""),
        )

        result.commit_sha = state.head_sha
        result.files_indexed = len(state.changed_files)
        result.schemas_found = len(state.schemas)
        return result
