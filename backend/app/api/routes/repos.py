import asyncio
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from git import Repo
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.workflow_tracker import tracker
from app.knowledge.chunker import chunk_document
from app.knowledge.doc_generator import DocGenerator
from app.knowledge.doc_store import DocStore
from app.knowledge.git_tracker import GitTracker
from app.knowledge.indexing_pipeline import (
    generate_summary_doc,
    run_pass1_profile,
    run_pass2_3_knowledge,
    run_pass4_enrich,
)
from app.knowledge.repo_analyzer import RepoAnalyzer
from app.knowledge.vector_store import VectorStore
from app.models.base import async_session_factory
from app.services.membership_service import MembershipService
from app.services.project_cache_service import ProjectCacheService
from app.services.project_service import ProjectService
from app.services.ssh_key_service import SshKeyService

logger = logging.getLogger(__name__)

router = APIRouter()
_project_svc = ProjectService()
_ssh_key_svc = SshKeyService()
_git_tracker = GitTracker()
_repo_analyzer = RepoAnalyzer(settings.repo_clone_base_dir)
_doc_store = DocStore()
_doc_generator = DocGenerator()
_vector_store = VectorStore()
_cache_svc = ProjectCacheService()

_membership_svc = MembershipService()
_indexing_locks: dict[str, asyncio.Lock] = {}
_indexing_tasks: dict[str, asyncio.Task] = {}


class RepoCheckRequest(BaseModel):
    repo_url: str
    ssh_key_id: str | None = None


class RepoCheckResponse(BaseModel):
    accessible: bool
    branches: list[str]
    default_branch: str | None = None
    error: str | None = None


@router.post("/check-access", response_model=RepoCheckResponse)
async def check_access(
    body: RepoCheckRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Verify SSH/HTTPS access to a repo and list its branches."""
    ssh_key_content: str | None = None
    ssh_key_passphrase: str | None = None
    if body.ssh_key_id:
        decrypted = await _ssh_key_svc.get_decrypted(db, body.ssh_key_id)
        if decrypted:
            ssh_key_content, ssh_key_passphrase = decrypted
        else:
            return RepoCheckResponse(
                accessible=False,
                branches=[],
                error="SSH key not found",
            )

    result = await asyncio.to_thread(
        _repo_analyzer.list_remote_refs,
        repo_url=body.repo_url,
        ssh_key_content=ssh_key_content,
        ssh_key_passphrase=ssh_key_passphrase,
    )
    return RepoCheckResponse(**result)


class IndexRequest(BaseModel):
    force_full: bool = False


class IndexResponse(BaseModel):
    status: str
    commit_sha: str
    files_indexed: int
    schemas_found: int
    workflow_id: str | None = None


@router.post("/{project_id}/index", status_code=202)
async def index_repo(
    project_id: str,
    body: IndexRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    body = body or IndexRequest()
    project = await _project_svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.repo_url:
        raise HTTPException(
            status_code=400,
            detail="Project has no repository URL configured",
        )

    lock = _indexing_locks.setdefault(project_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Indexing already in progress for this project",
        )

    wf_id = await tracker.begin(
        "index_repo",
        {"project_id": project_id, "repo_url": project.repo_url},
    )

    task = asyncio.create_task(
        _run_index_background(project_id, project, body, wf_id, lock),
    )
    _indexing_tasks[project_id] = task

    return JSONResponse(
        status_code=202,
        content={
            "status": "started",
            "workflow_id": wf_id,
        },
    )


async def _run_index_background(
    project_id: str, project, body: IndexRequest,
    wf_id: str, lock: asyncio.Lock,
) -> None:
    """Run the indexing pipeline as a background task with its own DB session."""
    async with lock:
        try:
            async with async_session_factory() as db:
                await _run_index(project_id, project, body, db, wf_id)
        except Exception as exc:
            logger.exception("Background indexing failed for project %s", project_id)
            await tracker.end(wf_id, "index_repo", "failed", str(exc))
        finally:
            _indexing_tasks.pop(project_id, None)


async def _run_index(
    project_id: str, project, body: IndexRequest,
    db: AsyncSession, wf_id: str,
) -> IndexResponse:
    async with tracker.step(wf_id, "resolve_ssh_key", "Decrypting SSH key"):
        ssh_key_content = None
        ssh_key_passphrase = None
        if project.ssh_key_id:
            decrypted = await _ssh_key_svc.get_decrypted(db, project.ssh_key_id)
            if decrypted:
                ssh_key_content, ssh_key_passphrase = decrypted

    async with tracker.step(
        wf_id, "clone_or_pull", f"Cloning/pulling {project.repo_url}",
    ):
        repo_dir = await asyncio.to_thread(
            _repo_analyzer.clone_or_pull,
            repo_url=project.repo_url,
            project_id=project_id,
            branch=project.repo_branch,
            ssh_key_content=ssh_key_content,
            ssh_key_passphrase=ssh_key_passphrase,
        )

    async with tracker.step(wf_id, "detect_changes", "Computing changed files"):
        head_sha = await asyncio.to_thread(_git_tracker.get_head_sha, repo_dir)
        if body.force_full:
            last_sha = None
        else:
            last_sha = await _git_tracker.get_last_indexed_sha(
                db, project_id, branch=project.repo_branch,
            )
        diff_result = await asyncio.to_thread(
            _git_tracker.get_changed_files, repo_dir, last_sha, head_sha,
        )
        changed_files = diff_result.changed
        deleted_files = diff_result.deleted
    await tracker.emit(
        wf_id, "detect_changes", "completed",
        f"{len(changed_files)} changed, {len(deleted_files)} deleted",
    )

    if deleted_files:
        async with tracker.step(
            wf_id, "cleanup_deleted",
            f"Removing {len(deleted_files)} deleted file(s) from knowledge base",
        ):
            await _doc_store.delete_docs_for_paths(db, project_id, deleted_files)
            for dpath in deleted_files:
                await asyncio.to_thread(
                    _vector_store.delete_by_source_path, project_id, dpath,
                )

    async with tracker.step(
        wf_id, "project_profile", "Detecting project framework and structure",
    ):
        cached_profile = await _cache_svc.load_profile(db, project_id)
        marker_overlap = False
        if cached_profile and not body.force_full:
            markers = cached_profile.marker_files
            marker_overlap = bool(markers & set(changed_files))

        if cached_profile and not body.force_full and not marker_overlap:
            profile = cached_profile
            logger.info("Using cached project profile")
        else:
            profile = await asyncio.to_thread(run_pass1_profile, repo_dir)
    await tracker.emit(
        wf_id, "project_profile", "completed", profile.summary,
    )

    async with tracker.step(
        wf_id, "analyze_files", f"Analyzing {len(changed_files)} files",
    ):
        raw_schemas = await asyncio.to_thread(
            _repo_analyzer.analyze, repo_dir, changed_files, profile,
        )
        merged: dict[str, object] = {}
        for s in raw_schemas:
            key = s.file_path
            if key in merged:
                existing = merged[key]
                existing.doc_type = (
                    s.doc_type if s.doc_type == "orm_model" else existing.doc_type
                )
                existing.models = list(
                    dict.fromkeys(existing.models + s.models),
                )
                existing.tables = list(
                    dict.fromkeys(existing.tables + s.tables),
                )
                if (
                    s.doc_type == "query_pattern"
                    and s.content not in existing.content
                ):
                    existing.content += f"\n\n---\n\n{s.content}"
            else:
                merged[key] = s
        schemas = list(merged.values())

    async with tracker.step(
        wf_id, "cross_file_analysis",
        "Building entity map, usage tracking, and enum extraction",
    ):
        cached_knowledge = None
        if not body.force_full:
            cached_knowledge = await _cache_svc.load_knowledge(
                db, project_id,
            )
        is_incremental = cached_knowledge is not None and last_sha is not None
        knowledge = await asyncio.to_thread(
            run_pass2_3_knowledge,
            repo_dir,
            schemas,
            changed_files=changed_files if is_incremental else None,
            deleted_files=deleted_files if is_incremental else None,
            cached_knowledge=cached_knowledge,
        )
    await tracker.emit(
        wf_id, "cross_file_analysis", "completed",
        f"{len(knowledge.entities)} entities, "
        f"{len(knowledge.dead_tables)} dead tables, "
        f"{len(knowledge.enums)} enums"
        + (" (incremental)" if is_incremental else " (full)"),
    )

    enriched_docs = await asyncio.to_thread(
        run_pass4_enrich, schemas, knowledge, profile,
    )

    summary_doc = generate_summary_doc(knowledge, profile)
    enriched_docs.append(summary_doc)

    existing_summary = await _doc_store.get_docs_for_project(
        db, project_id, doc_type="project_summary",
    )
    existing_summary_hash = ""
    if existing_summary:
        existing_summary_hash = hashlib.md5(
            existing_summary[0].content.encode(),
        ).hexdigest()

    doc_ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    async with tracker.step(
        wf_id, "generate_docs",
        f"Generating docs for {len(enriched_docs)} items",
    ):
        for i, edoc in enumerate(enriched_docs):
            await tracker.emit(
                wf_id, "generate_docs", "started",
                f"Processing {edoc.file_path} ({i + 1}/{len(enriched_docs)})",
            )

            if edoc.file_path == "__project_summary__":
                new_hash = hashlib.md5(edoc.content.encode()).hexdigest()
                if new_hash == existing_summary_hash:
                    logger.info(
                        "Project summary unchanged, skipping LLM call",
                    )
                    continue

            generated_content = await _doc_generator.generate(
                file_path=edoc.file_path,
                content=edoc.content,
                doc_type=edoc.doc_type,
                preferred_provider=project.default_llm_provider,
                model=project.default_llm_model,
                enrichment_context=edoc.enrichment_context,
            )

            doc = await _doc_store.upsert(
                session=db,
                project_id=project_id,
                doc_type=edoc.doc_type,
                source_path=edoc.file_path,
                content=generated_content,
                commit_sha=head_sha,
            )

            await asyncio.to_thread(
                _vector_store.delete_by_source_path,
                project_id, edoc.file_path,
            )

            chunks = chunk_document(
                content=generated_content,
                file_path=edoc.file_path,
                doc_type=edoc.doc_type,
                extra_metadata={
                    "commit_sha": head_sha,
                    "models": ",".join(edoc.models),
                    "tables": ",".join(edoc.tables),
                },
            )
            for chunk in chunks:
                chunk_id = (
                    f"{doc.id}:{chunk.metadata.get('chunk_index', '0')}"
                )
                doc_ids.append(chunk_id)
                documents.append(chunk.content)
                metadatas.append(chunk.metadata)

    async with tracker.step(
        wf_id, "chunk_and_store",
        f"Storing {len(doc_ids)} chunks in vector store",
    ):
        if doc_ids:
            await asyncio.to_thread(
                _vector_store.add_documents,
                project_id=project_id,
                doc_ids=doc_ids,
                documents=documents,
                metadatas=metadatas,
            )

    async with tracker.step(wf_id, "record_index", "Recording commit index"):
        repo = await asyncio.to_thread(Repo, str(repo_dir))
        commit_msg = repo.head.commit.message.strip()[:200]
        await _git_tracker.record_index(
            session=db,
            project_id=project_id,
            commit_sha=head_sha,
            commit_message=commit_msg,
            indexed_files=changed_files,
            branch=project.repo_branch,
        )
        await _git_tracker.cleanup_old_records(db, project_id, keep=10)
        await _cache_svc.save(
            db, project_id, knowledge=knowledge, profile=profile,
        )

    await tracker.end(
        wf_id, "index_repo", "completed",
        f"Indexed {len(changed_files)} files, {len(schemas)} schemas",
    )

    return IndexResponse(
        status="completed",
        commit_sha=head_sha,
        files_indexed=len(changed_files),
        schemas_found=len(schemas),
        workflow_id=wf_id,
    )


@router.get("/{project_id}/status")
async def repo_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _project_svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    record = await _git_tracker.get_last_indexed_record(
        db, project_id, branch=project.repo_branch,
    )
    docs = await _doc_store.get_docs_for_project(db, project_id)
    lock = _indexing_locks.get(project_id)

    indexed_files_count = 0
    if record and record.indexed_files:
        import json as _json
        try:
            indexed_files_count = len(_json.loads(record.indexed_files))
        except Exception:
            pass

    return {
        "project_id": project_id,
        "repo_url": project.repo_url,
        "last_indexed_commit": record.commit_sha if record else None,
        "last_indexed_at": (
            record.created_at.isoformat() if record and record.created_at else None
        ),
        "branch": record.branch if record else project.repo_branch,
        "indexed_files_count": indexed_files_count,
        "total_documents": len(docs),
        "is_indexing": bool(lock and lock.locked()),
    }


@router.post("/{project_id}/check-updates")
async def check_for_updates(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Quick check: fetch remote + compare HEAD with last indexed SHA."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _project_svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.repo_url:
        raise HTTPException(status_code=400, detail="No repository configured")

    repo_dir = _repo_analyzer.get_repo_dir(project_id)
    if not repo_dir.exists():
        return {
            "has_updates": True,
            "commits_behind": -1,
            "message": "Repository not yet cloned",
        }

    try:
        await asyncio.to_thread(_git_fetch, repo_dir)
    except Exception as exc:
        logger.warning("git fetch failed: %s", exc)

    last_sha = await _git_tracker.get_last_indexed_sha(
        db, project_id, branch=project.repo_branch,
    )
    if not last_sha:
        return {
            "has_updates": True,
            "commits_behind": -1,
            "message": "Not yet indexed",
        }

    head_sha = await asyncio.to_thread(_git_tracker.get_head_sha, repo_dir)
    if head_sha == last_sha:
        return {
            "has_updates": False,
            "commits_behind": 0,
            "message": "Up to date",
        }

    behind = await _git_tracker.count_commits_ahead(repo_dir, last_sha)
    return {
        "has_updates": True,
        "commits_behind": behind,
        "message": f"{behind} new commit(s) since last index",
    }


def _git_fetch(repo_dir) -> None:
    repo = Repo(str(repo_dir))
    for remote in repo.remotes:
        remote.fetch()


@router.get("/{project_id}/docs")
async def list_docs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List latest version of each indexed document for a project."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    docs = await _doc_store.get_latest_docs(db, project_id)
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "source_path": d.source_path,
            "commit_sha": d.commit_sha,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in docs
    ]


@router.get("/{project_id}/docs/{doc_id}")
async def get_doc(
    project_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get full content of a specific indexed document."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    docs = await _doc_store.get_docs_for_project(db, project_id)
    doc = next((d for d in docs if d.id == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "source_path": doc.source_path,
        "commit_sha": doc.commit_sha,
        "content": doc.content,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
