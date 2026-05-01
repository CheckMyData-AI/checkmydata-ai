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
from app.knowledge.doc_generator import _is_binary_content
from app.knowledge.indexing_pipeline import (
    generate_summary_doc,
    run_pass1_profile,
    run_pass2_3_knowledge,
    run_pass4_enrich,
)
from app.knowledge.repo_analyzer import is_binary_file
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
        live_table_names: list[str] | None = None,
    ) -> PipelineResult:
        cp_id = checkpoint.id
        done = await self._cp_svc.get_completed_steps(db, cp_id)
        resuming = len(done) > 0
        result = PipelineResult(resumed=resuming)
        state = _PipelineState()

        if resuming:
            result.resumed_from_step = sorted(done)[-1] if done else None
            already_processed = await self._cp_svc.get_processed_doc_paths(db, cp_id)
            await tracker.emit(
                wf_id,
                "pipeline_resume",
                "started",
                f"Resuming from checkpoint ({len(done)} steps done, "
                f"{len(already_processed)} docs processed)",
            )

        try:
            return await self._run_steps(
                project_id=project_id,
                project=project,
                force_full=force_full,
                db=db,
                wf_id=wf_id,
                checkpoint=checkpoint,
                cp_id=cp_id,
                done=done,
                resuming=resuming,
                result=result,
                state=state,
                live_table_names=live_table_names,
            )
        except Exception as exc:
            logger.exception("Indexing pipeline failed for project %s", project_id[:8])
            result.status = "failed"
            try:
                await self._cp_svc.complete_step(db, cp_id, "pipeline_failed")
            except Exception:
                logger.debug("Failed to update checkpoint on pipeline error", exc_info=True)
            try:
                await tracker.end(wf_id, "index_repo", "failed", str(exc))
            except Exception:
                logger.debug("Failed to emit pipeline failure event", exc_info=True)
            return result

    async def _run_steps(
        self,
        project_id: str,
        project,
        force_full: bool,
        db: AsyncSession,
        wf_id: str,
        checkpoint: IndexingCheckpoint,
        cp_id: str,
        done: set,
        resuming: bool,
        result: PipelineResult,
        state: _PipelineState,
        live_table_names: list[str] | None = None,
    ) -> PipelineResult:
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

        # --- Pre-filter: remove binary files from changed_files early ---
        if state.repo_dir and state.changed_files:
            before = len(state.changed_files)
            state.changed_files = [
                f
                for f in state.changed_files
                if (state.repo_dir / f).exists()
                and (state.repo_dir / f).is_file()
                and not is_binary_file(state.repo_dir / f)
            ]
            filtered = before - len(state.changed_files)
            if filtered:
                logger.info("Pre-filtered %d binary/missing files from changed_files", filtered)
                await tracker.emit(
                    wf_id,
                    "detect_changes",
                    "started",
                    f"Pre-filtered {filtered} binary/missing files, "
                    f"{len(state.changed_files)} files remaining",
                )

        # --- Guard: force full re-index when vector store lost data ---
        if (
            not force_full
            and state.last_sha is not None
            and not state.changed_files
            and not state.deleted_files
        ):
            try:
                col = self._vector_store.get_or_create_collection(project_id)
                if col.count() == 0:
                    existing_docs = await self._doc_store.get_docs_for_project(db, project_id)
                    if existing_docs:
                        logger.warning(
                            "Vector store empty but %d docs exist in DB — forcing full re-index",
                            len(existing_docs),
                        )
                        await tracker.emit(
                            wf_id,
                            "detect_changes",
                            "started",
                            f"Vector store empty but {len(existing_docs)} docs in DB, "
                            "forcing full re-index",
                        )
                        force_full = True
            except Exception:
                logger.warning("Failed to check vector store, forcing full re-index", exc_info=True)
                force_full = True

        # --- Early exit: nothing changed since last index ---
        if (
            not state.changed_files
            and not state.deleted_files
            and state.last_sha is not None
            and not force_full
        ):
            logger.info("No file changes detected, skipping doc generation")
            await tracker.emit(
                wf_id,
                "no_changes",
                "completed",
                "No file changes detected since last index, skipping doc generation",
            )
            return await self._record_and_finish(
                project_id=project_id,
                project=project,
                db=db,
                wf_id=wf_id,
                cp_id=cp_id,
                state=state,
                result=result,
                resuming=resuming,
                live_table_names=live_table_names,
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
                    total_deleted = len(state.deleted_files)
                    for del_idx, dpath in enumerate(state.deleted_files, 1):
                        await asyncio.to_thread(
                            self._vector_store.delete_by_source_path,
                            project_id,
                            dpath,
                        )
                        if del_idx % 5 == 0 or del_idx == total_deleted:
                            await tracker.emit(
                                wf_id,
                                "cleanup_deleted",
                                "started",
                                f"Removed vectors {del_idx}/{total_deleted}: {dpath}",
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
            await tracker.emit(
                wf_id,
                "analyze_files",
                "started",
                f"Found {len(raw_schemas)} raw schemas, merging duplicates",
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
            await tracker.emit(
                wf_id,
                "analyze_files",
                "started",
                f"Merged into {len(state.schemas)} unique file schemas",
            )

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
                await tracker.emit(
                    wf_id,
                    "cross_file_analysis",
                    "started",
                    f"Running {'incremental' if is_incremental else 'full'} analysis "
                    f"on {len(state.schemas)} schemas"
                    + (
                        f" (cached: {len(cached_knowledge.entities)} entities)"
                        if cached_knowledge
                        else ""
                    ),
                )
                state.knowledge = await asyncio.to_thread(
                    run_pass2_3_knowledge,
                    state.repo_dir,
                    state.schemas,
                    changed_files=state.changed_files if is_incremental else None,
                    deleted_files=state.deleted_files if is_incremental else None,
                    cached_knowledge=cached_knowledge,
                    detected_orms=state.profile.orms if state.profile else None,
                )
            assert state.knowledge is not None
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
        assert state.knowledge is not None
        state.enriched_docs = await asyncio.to_thread(
            run_pass4_enrich,
            state.schemas,
            state.knowledge,
            state.profile,
        )
        summary_doc = generate_summary_doc(state.knowledge, state.profile, live_table_names)
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
        processed_paths = await self._cp_svc.get_processed_doc_paths(db, cp_id)
        changed_set = set(state.changed_files)
        is_incremental = state.last_sha is not None and not force_full
        total = len(state.enriched_docs)
        skipped = 0
        batch_flush_size = 10

        await self._cp_svc.complete_step(db, cp_id, "enrich_docs", total_docs=total)

        # Pre-fetch all existing docs in one query to avoid N individual lookups
        existing_docs_map: dict[str, str] = {}
        if is_incremental:
            all_existing = await self._doc_store.get_docs_for_project(db, project_id)
            existing_docs_map = {d.source_path: d.content for d in all_existing}

        # Build table_model_map once instead of per-doc
        table_model_map: dict[str, str] = {}
        if state.knowledge:
            for ent_name, ent_info in state.knowledge.entities.items():
                if ent_info.table_name:
                    table_model_map[ent_info.table_name.lower()] = ent_name

        # Cache the git Repo instance for _git_show calls
        git_repo: Repo | None = None
        if state.repo_dir:
            try:
                git_repo = await asyncio.to_thread(Repo, str(state.repo_dir))
            except Exception:
                logger.debug("Could not open Repo at %s for git_show caching", state.repo_dir)

        _llm_sem = asyncio.Semaphore(3)

        async def _generate_one_doc(
            edoc: EnrichedDoc,
            existing_doc_content: str | None,
            prev_content: str | None,
        ) -> str:
            """Run the LLM call under a concurrency limiter."""
            async with _llm_sem:
                return await self._doc_generator.generate(
                    file_path=edoc.file_path,
                    content=edoc.content,
                    doc_type=edoc.doc_type,
                    preferred_provider=project.indexing_llm_provider,
                    model=project.indexing_llm_model,
                    enrichment_context=edoc.enrichment_context,
                    previous_content=prev_content,
                    existing_doc=existing_doc_content,
                )

        async with tracker.step(
            wf_id,
            "generate_docs",
            f"Generating docs for {total} items"
            + (f" ({len(processed_paths)} already done)" if processed_paths else ""),
        ):
            pending_paths: list[str] = []

            # Phase 1: filter out skip-able docs and prepare LLM tasks
            llm_tasks: list[tuple[int, EnrichedDoc, str | None, str | None]] = []
            docs_generated = 0

            for i, edoc in enumerate(state.enriched_docs):
                if edoc.file_path in processed_paths:
                    skipped += 1
                    continue

                if _is_binary_content(edoc.content):
                    logger.warning(
                        "Skipping binary-looking doc %s",
                        edoc.file_path,
                    )
                    skipped += 1
                    pending_paths.append(edoc.file_path)
                    if len(pending_paths) >= batch_flush_size:
                        await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                        pending_paths = []
                    continue

                if edoc.file_path == "__project_summary__":
                    new_hash = hashlib.md5(edoc.content.encode()).hexdigest()
                    if new_hash == existing_summary_hash:
                        logger.info("Project summary unchanged, skipping LLM call")
                        pending_paths.append(edoc.file_path)
                        if len(pending_paths) >= batch_flush_size:
                            await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                            pending_paths = []
                        continue

                existing_doc_content = existing_docs_map.get(edoc.file_path)

                if is_incremental:
                    if (
                        edoc.file_path not in changed_set
                        and edoc.file_path != "__project_summary__"
                        and existing_doc_content
                    ):
                        skipped += 1
                        pending_paths.append(edoc.file_path)
                        if len(pending_paths) >= batch_flush_size:
                            await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                            pending_paths = []
                        continue

                prev_content = None
                if is_incremental and existing_doc_content and git_repo and state.last_sha:
                    prev_content = await self._git_show_cached(
                        git_repo, state.last_sha, edoc.file_path
                    )

                llm_tasks.append((i, edoc, existing_doc_content, prev_content))

            await tracker.emit(
                wf_id,
                "generate_docs",
                "started",
                f"Prepared {len(llm_tasks)} docs for LLM generation, "
                f"{skipped} skipped (unchanged/binary)",
            )

            # Phase 2: run LLM calls in parallel batches, then persist sequentially
            total_llm_tasks = len(llm_tasks)
            llm_batch_size = 5
            for batch_start in range(0, len(llm_tasks), llm_batch_size):
                batch = llm_tasks[batch_start : batch_start + llm_batch_size]

                await tracker.emit(
                    wf_id,
                    "generate_docs",
                    "started",
                    f"Processing batch {batch_start // llm_batch_size + 1} "
                    f"({len(batch)} docs, {batch_start + len(batch)}/{len(llm_tasks)} total)",
                )

                generated_results = await asyncio.gather(
                    *[
                        _generate_one_doc(edoc, existing_doc_content, prev_content)
                        for _, edoc, existing_doc_content, prev_content in batch
                    ]
                )

                for (_, edoc, _, _), generated_content in zip(batch, generated_results):
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

                    extra_meta: dict[str, str] = {
                        "commit_sha": state.head_sha,
                        "models": ",".join(edoc.models),
                        "tables": ",".join(edoc.tables),
                    }
                    for idx_t, tbl in enumerate(edoc.tables[:10]):
                        tbl_lower = tbl.lower()
                        extra_meta[f"table_{idx_t}"] = tbl_lower
                        if tbl_lower in table_model_map:
                            extra_meta[f"table_{idx_t}_model"] = table_model_map[tbl_lower]
                    for idx_m, mdl in enumerate(edoc.models[:10]):
                        extra_meta[f"model_{idx_m}"] = mdl

                    chunks = chunk_document(
                        content=generated_content,
                        file_path=edoc.file_path,
                        doc_type=edoc.doc_type,
                        extra_metadata=extra_meta,
                    )
                    if chunks:
                        chunk_ids = [
                            f"{doc.id}:{c.metadata.get('chunk_index', '0')}" for c in chunks
                        ]
                        chunk_docs = [c.content for c in chunks]
                        chunk_metas = [c.metadata for c in chunks]
                        await asyncio.to_thread(
                            self._vector_store.add_documents,
                            project_id=project_id,
                            doc_ids=chunk_ids,
                            documents=chunk_docs,
                            metadatas=chunk_metas,
                        )

                    docs_generated += 1
                    await tracker.emit(
                        wf_id,
                        "generate_docs",
                        "started",
                        f"Generated {docs_generated}/{total_llm_tasks}: {edoc.file_path}",
                    )

                    pending_paths.append(edoc.file_path)
                    if len(pending_paths) >= batch_flush_size:
                        await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)
                        pending_paths = []

            if pending_paths:
                await self._cp_svc.mark_docs_batch_processed(db, cp_id, pending_paths)

        result.docs_skipped = skipped

        return await self._record_and_finish(
            project_id=project_id,
            project=project,
            db=db,
            wf_id=wf_id,
            cp_id=cp_id,
            state=state,
            result=result,
            resuming=resuming,
            live_table_names=live_table_names,
        )

    @staticmethod
    async def _git_show(repo_dir: Path, sha: str | None, file_path: str) -> str | None:
        """Load the raw content of *file_path* at commit *sha* via ``git show``.

        Returns ``None`` on any error (file didn't exist in that commit,
        binary, etc.) — callers should treat it as "no previous content".
        """
        if not sha:
            return None
        git_path = file_path.split("#")[0]
        try:
            repo = await asyncio.to_thread(Repo, str(repo_dir))
            blob = await asyncio.to_thread(lambda: repo.git.show(f"{sha}:{git_path}"))
            return blob if isinstance(blob, str) else None
        except Exception:
            return None

    @staticmethod
    async def _git_show_cached(repo: Repo, sha: str, file_path: str) -> str | None:
        """Like _git_show but reuses an existing Repo instance."""
        git_path = file_path.split("#")[0]
        try:
            blob = await asyncio.to_thread(lambda: repo.git.show(f"{sha}:{git_path}"))
            return blob if isinstance(blob, str) else None
        except Exception:
            return None

    async def _record_and_finish(
        self,
        project_id: str,
        project,
        db: AsyncSession,
        wf_id: str,
        cp_id: str,
        state: _PipelineState,
        result: PipelineResult,
        resuming: bool,
        live_table_names: list[str] | None = None,
    ) -> PipelineResult:
        """Record the index commit, save caches, cleanup checkpoint, and emit completion."""
        async with tracker.step(wf_id, "record_index", "Recording commit index"):
            await tracker.emit(
                wf_id,
                "record_index",
                "started",
                f"Recording commit {state.head_sha[:8]}",
            )
            repo = await asyncio.to_thread(Repo, str(state.repo_dir))
            commit_msg = str(repo.head.commit.message).strip()[:200]
            await self._git_tracker.record_index(
                session=db,
                project_id=project_id,
                commit_sha=state.head_sha,
                commit_message=commit_msg,
                indexed_files=state.changed_files,
                branch=project.repo_branch,
            )
            await self._git_tracker.cleanup_old_records(db, project_id, keep=10)

            await tracker.emit(
                wf_id,
                "record_index",
                "started",
                "Saving knowledge caches",
            )
            await self._cache_svc.save(
                db,
                project_id,
                knowledge=state.knowledge,
                profile=state.profile,
            )

            if state.changed_files:
                await tracker.emit(
                    wf_id,
                    "record_index",
                    "started",
                    "Marking DB index and sync as stale",
                )
                await self._mark_db_index_code_stale(db, project_id)
                await self._mark_sync_stale(db, project_id)

        await self._cp_svc.delete(db, cp_id)

        await tracker.end(
            wf_id,
            "index_repo",
            "completed",
            f"Indexed {len(state.changed_files)} files, {len(state.schemas)} schemas"
            + (f" (resumed, {result.docs_skipped} docs skipped)" if resuming else ""),
        )

        result.commit_sha = state.head_sha
        result.files_indexed = len(state.changed_files)
        result.schemas_found = len(state.schemas)
        return result

    @staticmethod
    async def _mark_db_index_code_stale(
        db: AsyncSession,
        project_id: str,
    ) -> None:
        """After a code re-index, mark all DB index entries for this project's
        connections as ``code_stale`` so the agent knows the code_match_status
        values may be outdated."""
        try:
            from sqlalchemy import update as sa_update

            from app.models.db_index import DbIndex
            from app.services.connection_service import ConnectionService

            conn_svc = ConnectionService()
            connections = await conn_svc.list_by_project(db, project_id)
            for conn in connections:
                await db.execute(
                    sa_update(DbIndex)
                    .where(DbIndex.connection_id == conn.id)
                    .where(DbIndex.code_match_status != "code_stale")
                    .values(code_match_status="code_stale")
                )
            await db.flush()
            logger.info(
                "Marked DB index code_match_status as stale for project %s",
                project_id[:8],
            )
        except Exception:
            logger.debug(
                "Failed to mark DB index as code-stale for project %s",
                project_id[:8],
                exc_info=True,
            )

    @staticmethod
    async def _mark_sync_stale(
        db: AsyncSession,
        project_id: str,
    ) -> None:
        """After a code re-index, mark code-DB sync as stale for this project."""
        try:
            from app.services.code_db_sync_service import CodeDbSyncService

            svc = CodeDbSyncService()
            await svc.mark_stale_for_project(db, project_id)
            logger.info(
                "Marked code-DB sync as stale for project %s",
                project_id[:8],
            )
        except Exception:
            logger.debug(
                "Failed to mark code-DB sync as stale for project %s",
                project_id[:8],
                exc_info=True,
            )
