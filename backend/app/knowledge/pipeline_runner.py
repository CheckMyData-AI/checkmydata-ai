"""Resumable indexing pipeline runner.

Wraps the multi-pass indexing logic with checkpoint-based state tracking
so that interrupted runs can be resumed from the last completed step.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from git import Repo
from sqlalchemy import update

from app.config import settings
from app.core.heartbeat import heartbeat
from app.core.workflow_tracker import tracker
from app.knowledge.ast_parser import ASTParser, ParsedFile
from app.knowledge.bm25_index import BM25Index
from app.knowledge.chunker import chunk_document
from app.knowledge.code_graph import CodeGraph, CodeGraphBuilder
from app.knowledge.code_symbol_chunker import make_chunker as _make_symbol_chunker
from app.knowledge.doc_generator import _is_binary_content
from app.knowledge.indexing_pipeline import (
    generate_summary_doc,
    run_pass1_profile,
    run_pass2_3_knowledge,
    run_pass4_enrich,
)
from app.knowledge.repo_analyzer import is_binary_file
from app.models.base import async_session_factory
from app.models.indexing_run import IndexingRun
from app.services.checkpoint_service import CheckpointService
from app.services.code_graph_service import CodeGraphService

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
    # M1: tree-sitter parsed files keyed by repo-relative path. Populated
    # only when ``settings.code_graph_enabled`` is True.
    parsed_files: dict[str, ParsedFile] = field(default_factory=dict)
    ast_unsupported_count: int = 0
    ast_skipped_count: int = 0
    # R3-3: changed files whose AST parse failed this run (raised, or produced
    # parse_errors). Their existing graph symbols must NOT be purged on an
    # incremental merge — keep the last-good symbols until a clean parse.
    ast_failed_files: set[str] = field(default_factory=set)
    # M2: code knowledge graph built from parsed files.
    code_graph: CodeGraph | None = None
    # Repo-relative paths whose LLM doc generation still failed after retry in
    # this run; persisted to ProjectCache so the next run re-queues them.
    failed_doc_paths: list[str] = field(default_factory=list)
    # Previously-failed paths re-injected into changed_files this run; used to
    # clear them from the persisted queue once they succeed.
    requeued_doc_paths: list[str] = field(default_factory=list)


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

        async def _hb() -> None:
            # RES-2: tick the IndexingRun projection while long emit-less steps
            # (clone_or_pull, ast_parse, code_symbol_embed, bm25_build) run, so
            # a live run is never reaped as stale. Targeted UPDATE — mirrors
            # daily_knowledge_sync_service and avoids racing the _on_event
            # projection on ``IndexingRun.version``.
            async with async_session_factory() as s:
                await s.execute(
                    update(IndexingRun)
                    .where(IndexingRun.workflow_id == wf_id, IndexingRun.status == "running")
                    .values(heartbeat_at=datetime.now(UTC))
                )
                await s.commit()

        try:
            async with heartbeat(_hb, interval_seconds=settings.heartbeat_interval_seconds):
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
                # R3-4: a transient diff failure degrades to a full re-list
                # (every current blob in ``changed``) with ``deleted=[]``, so
                # files removed since the last index would never be cleaned up.
                # Recover deletions by diffing the known doc paths against the
                # current tree. ``diff_error is None`` for clean diffs and for
                # the intentional missing-base full index (first-run / GC'd
                # base), where there is nothing reliable to diff against.
                if diff.diff_error and state.last_sha:
                    known_docs = await self._doc_store.get_docs_for_project(db, project_id)
                    known_paths = {d.source_path for d in known_docs if d.source_path}
                    recovered = self._recover_deletions_on_fallback(
                        current_files=diff.changed,
                        known_doc_paths=known_paths,
                    )
                    if recovered:
                        state.deleted_files = sorted(set(state.deleted_files) | set(recovered))
                        logger.warning(
                            "detect_changes: diff fell back to full re-list (%s); "
                            "recovered %d deletion(s) by diffing %d known doc paths",
                            diff.diff_error,
                            len(recovered),
                            len(known_paths),
                        )
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

        # --- Re-queue docs that failed generation in a previous run ---
        # A partial failure (under generate_docs_max_failure_ratio) lets the
        # run complete, but those paths are no longer in any future diff, so
        # without this they'd never get LLM content again. We splice them back
        # into changed_files (when the file still exists) so the normal
        # incremental machinery regenerates them.
        if not force_full and state.repo_dir is not None:
            try:
                prior_failed = await self._cache_svc.get_failed_doc_paths(db, project_id)
            except Exception:
                logger.debug("Failed to load prior failed doc paths", exc_info=True)
                prior_failed = []
            if prior_failed:
                existing_changed = set(state.changed_files)
                requeued = [
                    p
                    for p in prior_failed
                    if p not in existing_changed
                    and (state.repo_dir / p).exists()
                    and (state.repo_dir / p).is_file()
                    and not is_binary_file(state.repo_dir / p)
                ]
                if requeued:
                    state.changed_files.extend(requeued)
                    state.requeued_doc_paths = requeued
                    logger.info(
                        "Re-queued %d previously-failed doc(s) for regeneration",
                        len(requeued),
                    )
                    await tracker.emit(
                        wf_id,
                        "detect_changes",
                        "started",
                        f"Re-queued {len(requeued)} previously-failed doc(s) for regeneration",
                    )

        # --- Guard: vector store health (C3, v1.13.0) ---
        # Three distinct cases:
        #   1. Chroma reachable, collection legitimately empty AND no docs in
        #      DB — normal initial state, do nothing.
        #   2. Chroma reachable, collection empty BUT docs in DB — data
        #      corruption (Chroma volume lost). Emit a ``repair_embeddings``
        #      sub-step and force a full re-index so the embeddings are
        #      rebuilt from the existing KnowledgeDoc rows.
        #   3. Chroma unreachable — do NOT force_full and do NOT null
        #      ``last_sha``. We surface a warning so an operator sees it, but
        #      the indexing run continues with what we have. Force-re-indexing
        #      against an unreachable embedding backend would only burn LLM
        #      calls and produce no vectors.
        if (
            not force_full
            and state.last_sha is not None
            and not state.changed_files
            and not state.deleted_files
        ):
            try:
                col = self._vector_store.get_or_create_collection(project_id)
                col_count = col.count()
            except Exception:
                logger.warning(
                    "Vector store unreachable — preserving last_sha and skipping "
                    "embedding-health guard (C3 v1.13.0)",
                    exc_info=True,
                )
                await tracker.emit(
                    wf_id,
                    "detect_changes",
                    "warning",
                    "Vector store unreachable; preserving last_sha and skipping "
                    "embedding-health guard. Re-run indexing once Chroma is back online.",
                )
                col_count = None  # unknown — do nothing

            if col_count == 0:
                existing_docs = await self._doc_store.get_docs_for_project(db, project_id)
                if existing_docs:
                    logger.warning(
                        "Vector store empty but %d docs exist in DB — "
                        "running repair_embeddings (C3 v1.13.0)",
                        len(existing_docs),
                    )
                    await tracker.emit(
                        wf_id,
                        "repair_embeddings",
                        "started",
                        f"Vector store empty but {len(existing_docs)} docs in DB. "
                        "Forcing a full re-index to rebuild embeddings.",
                    )
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
            # R3-6: a no-op exit historically skipped the BM25 step entirely,
            # so a missing/stale snapshot (deleted .pkl, crashed prior build,
            # or sha drift) would never self-heal and the hybrid retriever
            # would degrade silently to dense-only. Verify + repair here.
            await self._repair_bm25_if_stale(db, project_id, state.head_sha, wf_id)
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

        # --- Step 5b: ast_parse (M1) ---
        # Tree-sitter AST extraction. Always re-runs because parsed files
        # are kept in-memory only and feed the graph_build step (M2).
        # Gated by code_graph_enabled; the step is a fast no-op when off.
        if settings.code_graph_enabled and state.repo_dir is not None:
            # A full parse walks every supported file; an incremental run only
            # touches the changed set and the graph is merged into the existing
            # one (see _run_graph_build) so unchanged files are preserved.
            is_full_graph = force_full or state.last_sha is None
            files_to_parse = await self._collect_files_for_ast(
                state.repo_dir,
                state.changed_files,
                force_full=is_full_graph,
            )
            async with tracker.step(
                wf_id,
                "ast_parse",
                f"Parsing AST for {len(files_to_parse)} file(s)",
            ):
                await self._run_ast_parse(state, wf_id, files_to_parse)
            await self._cp_svc.complete_step(db, cp_id, "ast_parse")

            # --- Step 5c: graph_build (M2) ---
            async with tracker.step(
                wf_id,
                "graph_build",
                f"Building code graph from {len(state.parsed_files)} parsed file(s)",
            ):
                graph_ok = await self._run_graph_build(
                    state, wf_id, db, project_id, is_full=is_full_graph
                )
            # C17: only checkpoint a build that actually succeeded — mirror the
            # bm25/clustering gate so a resume re-runs a crashed build.
            if graph_ok:
                await self._cp_svc.complete_step(db, cp_id, "graph_build")

            # --- Step 5d: code_symbol_embed (CODEIDX-C3) ---
            # Upsert raw symbol bodies into the vector store so code-Q&A
            # retrieval can surface actual function/class source, not only the
            # LLM-generated prose.  Gated on hybrid_retrieval_enabled (default
            # on) because that flag governs the broader "enhanced retrieval"
            # path; parsed_files is non-empty only when code_graph_enabled is
            # True, so this step is implicitly gated on both flags.
            if settings.hybrid_retrieval_enabled and state.parsed_files:
                symbol_count = sum(len(pf.symbols) for pf in state.parsed_files.values())
                async with tracker.step(
                    wf_id,
                    "code_symbol_embed",
                    f"Embedding {symbol_count} code symbols from {len(state.parsed_files)} file(s)",
                ):
                    await self._run_code_symbol_embed(state, project_id, wf_id)
                await self._cp_svc.complete_step(db, cp_id, "code_symbol_embed")

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

        # --- Pre-M5/M6: rehydrate code graph from DB when in-memory state is
        # empty. Two paths hit this branch:
        #   1) Incremental indexing where no files changed touched ast_parse,
        #      so ``state.parsed_files`` is empty and ``_run_graph_build``
        #      no-ops.
        #   2) graph_build raised; ``state.code_graph`` stays None, but the
        #      previous successful run still has a valid graph in Postgres.
        # Without this, M5/M6 silently skip on every resume.
        if (
            settings.code_graph_enabled
            and state.code_graph is None
            and (settings.lineage_enabled or settings.clustering_enabled)
        ):
            try:
                hydrated = await CodeGraphService().load_graph(db, project_id)
                if hydrated is not None:
                    state.code_graph = hydrated
                    logger.info(
                        "graph_rehydrate: loaded %d symbols from DB for project=%s",
                        len(hydrated.symbols),
                        project_id[:8],
                    )
            except Exception:
                logger.debug(
                    "graph_rehydrate failed for project %s",
                    project_id[:8],
                    exc_info=True,
                )

        # --- Step 7b: graph_db_bridge (M5) ---
        # Stitch the code graph's CALLS edges onto ORM entities so downstream
        # consumers (CodeDbSyncAnalyzer, SQLAgent) can answer "which endpoint
        # touches this table?". Cheap, in-memory; gated by lineage_enabled.
        if (
            settings.lineage_enabled
            and state.knowledge is not None
            and state.code_graph is not None
        ):
            async with tracker.step(
                wf_id,
                "graph_db_bridge",
                "Linking code graph callers to ORM entities",
            ):
                try:
                    from app.knowledge.graph_db_bridge import GraphDBBridge

                    bridge = GraphDBBridge(
                        max_depth=settings.lineage_max_depth,
                    )
                    attached = await asyncio.to_thread(
                        bridge.enrich,
                        state.knowledge,
                        state.code_graph,
                    )
                    try:
                        from app.core.metrics import get_metrics_collector

                        m = get_metrics_collector()
                        m.inc(
                            "code_graph_lineage_refs_total",
                            attached,
                            project=project_id[:8],
                        )
                    except Exception:
                        logger.debug("metrics emit failed for bridge", exc_info=True)
                    await tracker.emit(
                        wf_id,
                        "graph_db_bridge",
                        "completed",
                        f"Attached {attached} caller refs across "
                        f"{len(state.knowledge.entities)} entities",
                    )
                    # Re-persist knowledge so the lineage survives restarts.
                    await self._cp_svc.complete_step(
                        db,
                        cp_id,
                        "graph_db_bridge",
                        knowledge_json=state.knowledge.to_json(),
                    )
                except Exception:
                    logger.exception(
                        "graph_db_bridge failed for project %s; lineage skipped",
                        project_id[:8],
                    )
                    await tracker.emit(
                        wf_id,
                        "graph_db_bridge",
                        "failed",
                        "Bridge errored; continuing without lineage",
                    )

        # --- Step 7c: graph_clustering (M6) ---
        # Compute Louvain communities + (optionally) LLM-label them so the
        # SQL agent can answer "show me the auth tables" via one call.
        # Cheap in CPU but expensive in LLM tokens, so we gate label_clusters
        # behind a separate flag.
        if (
            settings.clustering_enabled
            and state.code_graph is not None
            and state.knowledge is not None
        ):
            async with tracker.step(
                wf_id,
                "graph_clustering",
                "Running Louvain community detection",
            ):
                clustering_ok = False
                cluster_count = 0
                try:
                    from app.knowledge.code_clustering import (
                        cluster_code_graph,
                        label_clusters,
                    )

                    clusters = await asyncio.to_thread(
                        cluster_code_graph,
                        state.code_graph,
                        state.knowledge,
                    )
                    if clusters and settings.cluster_llm_label_enabled:
                        # The runner doesn't carry an LLM router today; reach
                        # into the global router lazily so labeling stays a
                        # soft dependency (graceful default = "Cluster N").
                        try:
                            from app.llm.router import LLMRouter

                            llm_router = LLMRouter()
                        except Exception:
                            logger.debug(
                                "LLMRouter unavailable; skipping cluster labeling",
                                exc_info=True,
                            )
                            llm_router = None
                        if llm_router is not None:
                            await label_clusters(
                                clusters,
                                state.code_graph,
                                llm_router,
                                batch_size=10,
                            )
                    if clusters:
                        svc = CodeGraphService()
                        await svc.save_clusters(db, project_id, clusters)
                        await db.commit()
                    cluster_count = len(clusters)
                    clustering_ok = True
                    try:
                        from app.core.metrics import get_metrics_collector

                        m = get_metrics_collector()
                        m.inc(
                            "code_graph_clusters_total",
                            cluster_count,
                            project=project_id[:8],
                        )
                    except Exception:
                        logger.debug("metrics emit failed for clustering", exc_info=True)
                    await tracker.emit(
                        wf_id,
                        "graph_clustering",
                        "completed",
                        f"{cluster_count} clusters",
                    )
                except Exception:
                    logger.exception("graph_clustering failed for project %s", project_id[:8])
                    await tracker.emit(
                        wf_id,
                        "graph_clustering",
                        "failed",
                        "Clustering errored; continuing without clusters",
                    )
                # Only mark the step complete when we actually finished —
                # otherwise a later resume would treat the failure as "done"
                # and the model would consult a cluster table that may be
                # stale or empty.
                if clustering_ok:
                    await self._cp_svc.complete_step(db, cp_id, "graph_clustering")

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
                    # R3-7: ``_is_binary_content`` is a >30%-non-printable
                    # heuristic, and genuine binaries were already pre-filtered
                    # upstream, so a hit here is most likely a false positive
                    # (e.g. heavy-unicode source). Queue it for regeneration so
                    # it gets one more attempt on the next run instead of being
                    # silently lost until someone forces a full re-index.
                    if edoc.file_path not in state.failed_doc_paths:
                        state.failed_doc_paths.append(edoc.file_path)
                    # R3-7: do NOT checkpoint a binary skip as processed. It
                    # produced no doc and is queued for retry, so a resumed run
                    # (and the next full run via failed_doc_paths) must attempt
                    # it again rather than treating it as completed.
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
            # C2 (v1.13.0): per-doc failures must NOT abort the entire batch.
            # ``return_exceptions=True`` lets a single 5xx affect one doc only;
            # the rest of the batch persists. Failed docs are retried once
            # (capped) at the end of the loop, and if the cumulative failure
            # ratio exceeds ``settings.generate_docs_max_failure_ratio`` the
            # whole step fails so an operator sees the symptom.
            total_llm_tasks = len(llm_tasks)
            llm_batch_size = 5
            failed_doc_tasks: list[tuple[int, Any, str | None, str | None, str]] = []
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
                    ],
                    return_exceptions=True,
                )

                for (i_task, edoc, existing_doc_content, prev_content), generated in zip(
                    batch, generated_results
                ):
                    if isinstance(generated, BaseException):
                        err_msg = f"{type(generated).__name__}: {generated}"[:200]
                        logger.warning(
                            "generate_docs LLM failure for %s: %s",
                            edoc.file_path,
                            err_msg,
                        )
                        await tracker.emit(
                            wf_id,
                            "generate_docs.doc_failed",
                            "warning",
                            f"{edoc.file_path}: {err_msg}",
                        )
                        failed_doc_tasks.append(
                            (i_task, edoc, existing_doc_content, prev_content, err_msg)
                        )
                        continue

                    generated_content = generated
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

                    # Phase 2 (temporal chunk metadata): stamp each chunk with
                    # ``commit_sha`` + ``indexed_at`` so retrieval can reason about
                    # freshness and the orchestrator can tell *when* a RAG chunk
                    # was produced (closes the RAG temporal gap, plan §1.1/§Quick
                    # win #3). ``source_path`` is already added by ``chunk_document``.
                    extra_meta: dict[str, str] = {
                        "commit_sha": state.head_sha,
                        "indexed_at": datetime.now(UTC).isoformat(),
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

            # C2 (v1.13.0): bounded retry for docs that failed in their batch
            # (cap = 1 retry per doc). Final, unrecoverable failures bubble
            # into the failure-ratio gate below.
            still_failed: list[tuple[Any, str]] = []
            if failed_doc_tasks:
                await tracker.emit(
                    wf_id,
                    "generate_docs",
                    "started",
                    f"Retrying {len(failed_doc_tasks)} failed doc(s) (cap=1 each)",
                )
                await asyncio.sleep(1.0)
                retry_results = await asyncio.gather(
                    *[
                        _generate_one_doc(edoc, existing_doc_content, prev_content)
                        for _, edoc, existing_doc_content, prev_content, _ in failed_doc_tasks
                    ],
                    return_exceptions=True,
                )
                for (_, edoc, _, _, prev_err), retry_out in zip(failed_doc_tasks, retry_results):
                    if isinstance(retry_out, BaseException):
                        msg = f"{type(retry_out).__name__}: {retry_out}"[:200]
                        still_failed.append((edoc, msg))
                        await tracker.emit(
                            wf_id,
                            "generate_docs.doc_failed",
                            "warning",
                            f"{edoc.file_path} (retry): {msg}",
                        )
                    else:
                        try:
                            doc = await self._doc_store.upsert(
                                session=db,
                                project_id=project_id,
                                doc_type=edoc.doc_type,
                                source_path=edoc.file_path,
                                content=retry_out,
                                commit_sha=state.head_sha,
                            )
                            await asyncio.to_thread(
                                self._vector_store.delete_by_source_path,
                                project_id,
                                edoc.file_path,
                            )
                            chunks = chunk_document(
                                content=retry_out,
                                file_path=edoc.file_path,
                                doc_type=edoc.doc_type,
                                extra_metadata={
                                    "commit_sha": state.head_sha,
                                    "indexed_at": datetime.now(UTC).isoformat(),
                                },
                            )
                            if chunks:
                                chunk_ids = [
                                    f"{doc.id}:{c.metadata.get('chunk_index', '0')}" for c in chunks
                                ]
                                await asyncio.to_thread(
                                    self._vector_store.add_documents,
                                    project_id=project_id,
                                    doc_ids=chunk_ids,
                                    documents=[c.content for c in chunks],
                                    metadatas=[c.metadata for c in chunks],
                                )
                            docs_generated += 1
                            await self._cp_svc.mark_docs_batch_processed(
                                db, cp_id, [edoc.file_path]
                            )
                        except Exception as exc:
                            still_failed.append((edoc, str(exc)[:200]))
                            logger.warning(
                                "generate_docs retry persist failed for %s",
                                edoc.file_path,
                                exc_info=True,
                            )

            # Remember which paths still have no LLM content so the next run
            # re-queues them (see the re-queue block after detect_changes).
            # R3-7: union (don't overwrite) so binary-skipped paths appended in
            # Phase 1 above survive to persistence; overwriting dropped them and
            # silently negated the binary re-queue fix.
            state.failed_doc_paths = sorted(
                set(state.failed_doc_paths) | {edoc.file_path for edoc, _ in still_failed}
            )

            if total_llm_tasks > 0 and still_failed:
                failure_ratio = len(still_failed) / total_llm_tasks
                threshold = settings.generate_docs_max_failure_ratio
                if failure_ratio > threshold:
                    fail_msg = (
                        f"generate_docs failure ratio "
                        f"{failure_ratio:.0%} exceeded threshold {threshold:.0%}: "
                        f"{len(still_failed)} of {total_llm_tasks} docs failed"
                    )
                    logger.error(fail_msg)
                    await tracker.emit(
                        wf_id,
                        "generate_docs",
                        "failed",
                        fail_msg,
                    )
                    raise RuntimeError(fail_msg)
                else:
                    await tracker.emit(
                        wf_id,
                        "generate_docs.partial_completion",
                        "warning",
                        f"Completed with {len(still_failed)} doc failure(s) "
                        f"({failure_ratio:.0%}, under {threshold:.0%} threshold)",
                    )

        result.docs_skipped = skipped

        # --- Step 10: bm25_build (M3) ---
        # Rebuild the BM25 lexical index from the just-persisted KnowledgeDoc
        # rows. Full replace per indexing run -- cheap (in-process tokenization)
        # and avoids drift between Chroma and BM25.
        if settings.hybrid_retrieval_enabled:
            async with tracker.step(
                wf_id,
                "bm25_build",
                "Rebuilding BM25 lexical index",
            ):
                bm25_ok = await self._run_bm25_build(db, project_id, state.head_sha, wf_id)
            # A failed BM25 build must NOT mark the step complete — otherwise a
            # resume would skip the rebuild and the hybrid retriever would
            # degrade silently to dense-only against a missing/stale snapshot.
            if bm25_ok:
                await self._cp_svc.complete_step(db, cp_id, "bm25_build")

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

    async def _run_bm25_build(
        self,
        db: AsyncSession,
        project_id: str,
        head_sha: str,
        wf_id: str,
    ) -> bool:
        """Rebuild the project's BM25 snapshot from current KnowledgeDoc rows.

        Tokenization uses the same code-aware tokenizer the retriever does, so
        ranking is consistent across build and query time. Failures here are
        non-fatal at the pipeline level (we still return), but the caller
        must NOT checkpoint the step on a ``False`` return -- that's how we
        keep the resume path honest about whether a fresh snapshot exists.
        """
        try:
            docs = await self._doc_store.get_docs_for_project(db, project_id)
            bm25_docs: list[tuple[str, str, dict]] = []
            for doc in docs:
                chunks = chunk_document(
                    content=doc.content,
                    file_path=doc.source_path,
                    doc_type=doc.doc_type,
                )
                if not chunks:
                    chunks = []
                for chunk in chunks:
                    chunk_id = f"{doc.id}:{chunk.metadata.get('chunk_index', '0')}"
                    meta = dict(chunk.metadata)
                    meta.setdefault("source_path", doc.source_path)
                    meta.setdefault("doc_type", doc.doc_type)
                    bm25_docs.append((chunk_id, chunk.content, meta))
            bm25 = BM25Index(settings.bm25_data_dir)
            await asyncio.to_thread(bm25.build, project_id, head_sha, bm25_docs)
            logger.info(
                "bm25_build: project=%s docs=%d chunks=%d",
                project_id[:8],
                len(docs),
                len(bm25_docs),
            )
            await tracker.emit(
                wf_id,
                "bm25_build",
                "completed",
                f"Indexed {len(bm25_docs)} chunks from {len(docs)} docs",
            )
            return True
        except Exception as exc:
            logger.exception("bm25_build failed for project %s", project_id[:8])
            await tracker.emit(
                wf_id,
                "bm25_build",
                "failed",
                f"BM25 build failed: {exc!s}",
            )
            return False

    async def _repair_bm25_if_stale(
        self,
        db: AsyncSession,
        project_id: str,
        head_sha: str,
        wf_id: str,
    ) -> None:
        """Rebuild the BM25 snapshot if missing or out of sync with *head_sha*.

        R3-6: called on the no-change early-exit path so a deleted/corrupt/
        stale ``.pkl`` self-heals instead of silently degrading the hybrid
        retriever to dense-only. No-op when hybrid retrieval is disabled or the
        snapshot already matches the current head.
        """
        if not settings.hybrid_retrieval_enabled:
            return
        try:
            bm25 = BM25Index(settings.bm25_data_dir)
            current_sha = await asyncio.to_thread(bm25.indexed_sha, project_id)
            if current_sha == head_sha:
                return
            logger.warning(
                "BM25 snapshot stale on no-op run (project=%s have=%s want=%s); repairing",
                project_id[:8],
                current_sha,
                head_sha,
            )
            await tracker.emit(
                wf_id,
                "bm25_build",
                "started",
                "BM25 snapshot missing/stale on no-op run — repairing",
            )
            await self._run_bm25_build(db, project_id, head_sha, wf_id)
        except Exception:
            logger.debug("BM25 staleness repair check failed", exc_info=True)

    @staticmethod
    async def _collect_files_for_ast(
        repo_dir: Path,
        changed_files: list[str],
        force_full: bool,
    ) -> list[str]:
        """Pick the file list for the AST parse + graph build steps.

        On a full re-index we walk every supported source file so the graph
        has the full picture. On incremental runs we limit ourselves to the
        changed set; this keeps cost proportional to user activity but means
        the graph is locally accurate, not globally complete -- a tradeoff
        documented in the M2 plan.
        """
        from app.knowledge.ast_parser import detect_language
        from app.knowledge.shared_ignore import is_ignored_path

        if not force_full:
            return [
                f
                for f in changed_files
                if f
                and not f.endswith("/")
                and not is_ignored_path(f)
                and not is_binary_file(repo_dir / f)
            ]

        def _walk() -> list[str]:
            out: list[str] = []
            for path in repo_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(repo_dir)).replace("\\", "/")
                if is_ignored_path(rel):
                    continue
                if any(
                    part.startswith(".") and part not in (".",)
                    for part in path.relative_to(repo_dir).parts
                ):
                    continue
                if detect_language(path) is None:
                    continue
                out.append(rel)
            return out

        return await asyncio.to_thread(_walk)

    async def _run_code_symbol_embed(
        self,
        state: _PipelineState,
        project_id: str,
        wf_id: str,
    ) -> None:
        """CODEIDX-C3: upsert raw code-symbol chunks into the vector store.

        Runs synchronously in a thread (via ``asyncio.to_thread``) to avoid
        blocking the event loop on disk I/O and ChromaDB upserts.  Failures
        here are non-fatal — the pipeline continues without raw-code chunks if
        something goes wrong.
        """
        if state.repo_dir is None or not state.parsed_files:
            return
        try:
            chunker = _make_symbol_chunker()
            repo_dir = state.repo_dir
            parsed_files = state.parsed_files
            vs = self._vector_store
            await asyncio.to_thread(
                chunker.embed_symbols,
                project_id,
                parsed_files,
                repo_dir,
                vs,
            )
            symbol_count = sum(len(pf.symbols) for pf in parsed_files.values())
            logger.info(
                "code_symbol_embed: upserted symbols from %d file(s) (%d total symbols)",
                len(parsed_files),
                symbol_count,
            )
            await tracker.emit(
                wf_id,
                "code_symbol_embed",
                "completed",
                f"Upserted code symbols from {len(parsed_files)} file(s) ({symbol_count} symbols)",
            )
        except Exception:
            logger.warning(
                "code_symbol_embed: non-fatal failure for project %s",
                project_id,
                exc_info=True,
            )
            await tracker.emit(
                wf_id,
                "code_symbol_embed",
                "warning",
                "code_symbol_embed encountered an error — raw-code chunks skipped",
            )

    async def _run_ast_parse(
        self,
        state: _PipelineState,
        wf_id: str,
        files: list[str] | None = None,
    ) -> None:
        """M1: parse the given files with tree-sitter, populating state.parsed_files.

        This step is best-effort and never raises; per-file failures are caught
        and counted so the rest of the pipeline always proceeds.
        """
        if state.repo_dir is None:
            return
        parser = ASTParser(
            max_file_bytes=settings.ast_max_file_bytes,
            parse_error_ratio=settings.ast_parse_error_ratio,
        )
        sem = asyncio.Semaphore(max(1, settings.ast_parse_concurrency))
        repo_root = state.repo_dir
        target_files = files if files is not None else state.changed_files

        parsed_count = 0
        unsupported = 0
        skipped = 0
        errors = 0
        total_symbols = 0
        total_imports = 0

        async def _parse_one(rel_path: str) -> None:
            nonlocal parsed_count, unsupported, skipped, errors
            nonlocal total_symbols, total_imports
            async with sem:
                try:
                    parsed = await asyncio.to_thread(parser.parse_file, repo_root, rel_path)
                except Exception as exc:
                    errors += 1
                    # R3-3: a hard parse failure on a changed file — preserve
                    # its last-good symbols rather than purging on merge.
                    state.ast_failed_files.add(rel_path)
                    logger.debug("ast_parse: %s raised %s", rel_path, exc, exc_info=True)
                    return
            if parsed is None:
                unsupported += 1
                return
            if parsed.parse_errors:
                skipped += 1
                # R3-3: a syntactically broken file yields partial/zero symbols;
                # treat it as a parse failure so we don't drop its known symbols.
                state.ast_failed_files.add(rel_path)
                # Keep the record so the graph builder can see attempted files;
                # downstream consumers gate on symbols/imports presence.
            state.parsed_files[rel_path] = parsed
            parsed_count += 1
            total_symbols += len(parsed.symbols)
            total_imports += len(parsed.imports)

        tasks = [
            asyncio.create_task(_parse_one(rp))
            for rp in target_files
            if rp and not rp.endswith("/")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        state.ast_unsupported_count = unsupported
        state.ast_skipped_count = skipped

        logger.info(
            "ast_parse: parsed=%d unsupported=%d skipped=%d errors=%d symbols=%d imports=%d",
            parsed_count,
            unsupported,
            skipped,
            errors,
            total_symbols,
            total_imports,
        )
        await tracker.emit(
            wf_id,
            "ast_parse",
            "completed",
            f"Parsed {parsed_count} file(s): {total_symbols} symbols, "
            f"{total_imports} imports ({unsupported} unsupported, {skipped} skipped)",
        )

    @staticmethod
    def _recover_deletions_on_fallback(
        *,
        current_files: list[str],
        known_doc_paths: set[str],
    ) -> list[str]:
        """R3-4: when the incremental git diff degrades to a full re-list,
        deletions are lost (``deleted=[]``). Recover them by diffing the
        previously-indexed doc paths against the current full tree: any known
        doc whose source path is no longer present was deleted.

        ``current_files`` is the full blob list from the fallback re-list, so
        files that still exist (including binaries) are never flagged.
        """
        current = set(current_files)
        return sorted(p for p in known_doc_paths if p not in current)

    async def _run_graph_build(
        self,
        state: _PipelineState,
        wf_id: str,
        db: AsyncSession,
        project_id: str,
        *,
        is_full: bool = True,
    ) -> bool:
        """M2: build the code knowledge graph from parsed files and persist it.

        On a full run the graph fully replaces the persisted one. On an
        incremental run (``is_full=False``) only the changed files were parsed,
        so the freshly-built subset is merged into the existing graph via
        :meth:`CodeGraphService.save_incremental`; symbols/edges for changed and
        deleted files are replaced while unchanged files are preserved.

        Failures here are non-fatal: the graph is an additive signal, and the
        legacy regex pipeline still produces the canonical EntityInfo data.

        Returns ``True`` on success (including legitimate no-op skips) and
        ``False`` when an exception is caught, so the caller can gate
        ``complete_step`` on a real success (C17).
        """
        if not state.parsed_files and is_full:
            logger.info("graph_build: no parsed files, skipping")
            return True
        try:
            builder = CodeGraphBuilder(
                max_symbols=settings.code_graph_max_symbols,
                min_call_confidence=settings.code_graph_call_confidence_threshold,
            )
            graph = await asyncio.to_thread(builder.build, state.parsed_files)
            svc = CodeGraphService()
            if is_full:
                state.code_graph = graph
                sym_count, edge_count = await svc.save(db, project_id, graph)
            else:
                changed = set(state.changed_files)
                deleted = set(state.deleted_files)
                # C4: expand the parse set to the reverse-dependency closure of
                # the changed files so unchanged callers re-resolve their
                # CALLS/IMPORTS edges against the callee's current symbols.
                # We load the pre-merge graph once here (cheap: symbols already
                # in DB) and compute which files import anything from `changed`.
                # Those files are added to state.parsed_files if not already
                # present, and included in affected_files so their stale edges
                # are pruned before the fresh re-parsed edges splice in.
                existing_for_rdeps = await svc.load_graph(db, project_id)
                extra_files: set[str] = set()
                if existing_for_rdeps is not None:
                    extra_files = CodeGraphBuilder.reverse_dependents(existing_for_rdeps, changed)
                    extra_files -= changed | deleted
                    missing_from_parse = [f for f in extra_files if f not in state.parsed_files]
                    if missing_from_parse and state.repo_dir is not None:
                        logger.info(
                            "graph_build: re-parsing %d reverse-dependent file(s) "
                            "for C4 cross-file edge resolution: %s",
                            len(missing_from_parse),
                            sorted(missing_from_parse)[:10],
                        )
                        await self._run_ast_parse(state, wf_id, missing_from_parse)
                        # Rebuild the graph now that the reverse-deps are parsed.
                        graph = await asyncio.to_thread(builder.build, state.parsed_files)
                # R3-3: a changed file whose AST parse failed this run produced
                # no (or partial) symbols. Purging it on merge would wrongly
                # drop its last-good symbols, so exclude it from the affected
                # set — its existing graph rows are preserved until a clean
                # parse reconciles them. Deletions are always purged.
                failed = state.ast_failed_files & changed
                reconciled_changed = changed - failed
                # If *every* changed file failed to parse, skip the merge
                # entirely and keep the last-good graph (a later run retries).
                if not graph.symbols and reconciled_changed:
                    logger.warning(
                        "graph_build: incremental build produced 0 symbols for %d "
                        "cleanly-changed file(s) (likely parse failure); skipping merge "
                        "to preserve graph",
                        len(reconciled_changed),
                    )
                    merged = await svc.load_graph(db, project_id)
                    state.code_graph = merged if merged is not None else graph
                    await tracker.emit(
                        wf_id,
                        "graph_build",
                        "skipped",
                        "Incremental graph build produced no symbols (parse failure?); "
                        "kept existing graph",
                    )
                    return True
                if failed:
                    logger.info(
                        "graph_build: preserving symbols for %d changed file(s) that "
                        "failed to parse this run: %s",
                        len(failed),
                        sorted(failed)[:5],
                    )
                # C4: include reverse-dependents so their stale edges are
                # pruned from the existing graph before the re-parsed fresh
                # edges splice in.
                affected_files = reconciled_changed | deleted | extra_files
                sym_count, edge_count = await svc.save_incremental(
                    db, project_id, graph, affected_files
                )
                # Rehydrate the merged graph so downstream M5/M6 steps see the
                # full picture, not just the changed-file subset.
                merged = await svc.load_graph(db, project_id)
                state.code_graph = merged if merged is not None else graph
            # M6: observability counters.
            try:
                from app.core.metrics import get_metrics_collector

                m = get_metrics_collector()
                m.inc(
                    "code_graph_symbols_total",
                    sym_count,
                    project=project_id[:8],
                )
                m.inc(
                    "code_graph_edges_total",
                    edge_count,
                    project=project_id[:8],
                )
                m.inc("code_graph_builds_total", project=project_id[:8])
            except Exception:
                logger.debug("metrics emit failed for graph_build", exc_info=True)
            await tracker.emit(
                wf_id,
                "graph_build",
                "completed",
                f"Persisted {sym_count} symbols, {edge_count} edges",
            )
            return True
        except Exception as exc:
            logger.exception("graph_build failed for project %s: %s", project_id[:8], exc)
            await tracker.emit(
                wf_id,
                "graph_build",
                "failed",
                f"Graph build failed: {exc!s}",
            )
            return False

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

            # Persist the regeneration queue: this run's still-failed docs plus
            # any previously-queued paths we did NOT manage to retry this run,
            # minus the ones that just succeeded. requeued_doc_paths that are
            # not in failed_doc_paths succeeded and are dropped.
            try:
                prior_failed = await self._cache_svc.get_failed_doc_paths(db, project_id)
                requeued = set(state.requeued_doc_paths)
                still_failed = set(state.failed_doc_paths)
                # Keep prior entries we never got to retry (not requeued this run),
                # union with anything that failed this run.
                pending = (set(prior_failed) - requeued) | still_failed
                await self._cache_svc.set_failed_doc_paths(db, project_id, sorted(pending))
            except Exception:
                # R3-7: this was a debug-level swallow, so a failure to persist
                # the regeneration queue meant failed docs silently never got
                # retried with no visible signal. Surface it at warning level
                # (still non-fatal: the index commit itself already succeeded).
                logger.warning(
                    "Failed to persist doc regeneration queue for project %s; "
                    "failed docs may not be retried on the next run",
                    project_id[:8],
                    exc_info=True,
                )

            await self._maybe_mark_stale(db=db, project_id=project_id, state=state, wf_id=wf_id)

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

    async def _maybe_mark_stale(
        self,
        *,
        db,
        project_id: str,
        state: _PipelineState,
        wf_id: str = "",
    ) -> None:
        """Mark DB index and sync as stale only when real file changes occurred."""
        if state.changed_files or state.deleted_files:
            await tracker.emit(
                wf_id,
                "record_index",
                "started",
                "Marking DB index and sync as stale",
            )
            await self._mark_db_index_code_stale(db, project_id)
            await self._mark_sync_stale(db, project_id)

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
