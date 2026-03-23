import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from git import Repo
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.core.workflow_tracker import tracker
from app.knowledge.doc_generator import DocGenerator
from app.knowledge.doc_store import DocStore
from app.knowledge.git_tracker import GitTracker
from app.knowledge.pipeline_runner import IndexingPipelineRunner
from app.knowledge.repo_analyzer import RepoAnalyzer
from app.knowledge.vector_store import VectorStore
from app.models.base import async_session_factory
from app.services.checkpoint_service import CheckpointService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_cache_service import ProjectCacheService
from app.services.project_service import ProjectService
from app.services.repository_service import RepositoryService
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
_checkpoint_svc = CheckpointService()

_connection_svc = ConnectionService()
_membership_svc = MembershipService()
_repo_svc = RepositoryService()
_indexing_locks: dict[str, asyncio.Lock] = {}
_indexing_tasks: dict[str, asyncio.Task] = {}
_index_start_locks: dict[str, asyncio.Lock] = {}

_pipeline_runner = IndexingPipelineRunner(
    ssh_key_svc=_ssh_key_svc,
    git_tracker=_git_tracker,
    repo_analyzer=_repo_analyzer,
    doc_store=_doc_store,
    doc_generator=_doc_generator,
    vector_store=_vector_store,
    cache_svc=_cache_svc,
    checkpoint_svc=_checkpoint_svc,
)


class RepoCheckRequest(BaseModel):
    repo_url: str
    ssh_key_id: str | None = None


class RepoCheckResponse(BaseModel):
    accessible: bool
    branches: list[str]
    default_branch: str | None = None
    error: str | None = None


@router.post("/check-access", response_model=RepoCheckResponse)
@limiter.limit("10/minute")
async def check_access(
    request: Request,
    body: RepoCheckRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Verify SSH/HTTPS access to a repo and list its branches."""
    ssh_key_content: str | None = None
    ssh_key_passphrase: str | None = None
    if body.ssh_key_id:
        decrypted = await _ssh_key_svc.get_decrypted(db, body.ssh_key_id, user_id=user["user_id"])
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
@limiter.limit("5/minute")
async def index_repo(
    request: Request,
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

    start_lock = _index_start_locks.setdefault(project_id, asyncio.Lock())
    async with start_lock:
        existing_task = _indexing_tasks.get(project_id)
        if existing_task and not existing_task.done():
            raise HTTPException(
                status_code=409,
                detail="Indexing already in progress for this project",
            )

        lock = _indexing_locks.setdefault(project_id, asyncio.Lock())

        existing_cp = await _checkpoint_svc.get_active(db, project_id)
        resumed = False

        if existing_cp and not body.force_full:
            if existing_cp.status == "running":
                existing_cp.status = "interrupted"
                await db.commit()
            resumed = True
        elif existing_cp and body.force_full:
            await _checkpoint_svc.delete(db, existing_cp.id)
            existing_cp = None

        logger.info(
            "Index started: project=%s force=%s resumed=%s",
            project_id[:8],
            body.force_full,
            resumed,
        )

        wf_id = await tracker.begin(
            "index_repo",
            {
                "project_id": project_id,
                "repo_url": project.repo_url,
                "resumed": resumed,
            },
        )

        def _on_index_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error("Repo index %s failed: %s", project_id, exc, exc_info=exc)

        task = asyncio.create_task(
            _run_index_background(project_id, project, body, wf_id, lock),
        )
        task.add_done_callback(_on_index_done)
        _indexing_tasks[project_id] = task

    return JSONResponse(
        status_code=202,
        content={
            "status": "resumed" if resumed else "started",
            "workflow_id": wf_id,
            "resumed": resumed,
        },
    )


async def _regenerate_overview(project_id: str) -> None:
    """Best-effort regenerate the project knowledge overview."""
    from app.services.project_overview_service import ProjectOverviewService

    try:
        async with async_session_factory() as session:
            svc = ProjectOverviewService()
            await svc.save_overview(session, project_id)
        logger.info("Project overview regenerated after repo index: project=%s", project_id[:8])
    except Exception:
        logger.warning("Failed to regenerate project overview", exc_info=True)


async def _run_index_background(
    project_id: str,
    project,
    body: IndexRequest,
    wf_id: str,
    lock: asyncio.Lock,
) -> None:
    """Run the indexing pipeline as a background task with its own DB session."""
    async with lock:
        try:
            async with async_session_factory() as db:
                existing_cp = await _checkpoint_svc.get_active(db, project_id)

                if existing_cp and not body.force_full:
                    existing_cp.workflow_id = wf_id
                    existing_cp.status = "running"
                    await db.commit()
                    await db.refresh(existing_cp)
                    checkpoint = existing_cp
                else:
                    checkpoint = await _checkpoint_svc.create(
                        db,
                        project_id,
                        wf_id,
                        head_sha="",
                        last_sha=None,
                    )

                live_table_names = await _fetch_live_table_names(db, project_id)

                try:
                    await _pipeline_runner.run(
                        project_id,
                        project,
                        body.force_full,
                        db,
                        wf_id,
                        checkpoint,
                        live_table_names=live_table_names,
                    )
                    await _regenerate_overview(project_id)
                except Exception as exc:
                    logger.exception("Indexing pipeline failed for project %s", project_id)
                    try:
                        cp = await _checkpoint_svc.get_active(db, project_id)
                        if cp:
                            await _checkpoint_svc.mark_failed(db, cp.id, "pipeline", str(exc))
                    except Exception:
                        logger.exception(
                            "Failed to mark checkpoint as failed for project %s", project_id
                        )
                    await tracker.end(wf_id, "index_repo", "failed", str(exc))
        except Exception as exc:
            logger.exception("Background indexing failed for project %s", project_id)
            await tracker.end(wf_id, "index_repo", "failed", str(exc))
        finally:
            _indexing_tasks.pop(project_id, None)


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
        db,
        project_id,
        branch=project.repo_branch,
    )
    docs = await _doc_store.get_docs_for_project(db, project_id)

    indexed_files_count = 0
    if record and record.indexed_files:
        import json as _json

        try:
            indexed_files_count = len(_json.loads(record.indexed_files))
        except Exception:
            pass

    checkpoint = await _checkpoint_svc.get_active(db, project_id)

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
        "is_indexing": bool(
            _indexing_tasks.get(project_id) and not _indexing_tasks[project_id].done()
        ),
        "has_checkpoint": checkpoint is not None,
        "checkpoint_status": checkpoint.status if checkpoint else None,
    }


@router.post("/{project_id}/check-updates")
@limiter.limit("10/minute")
async def check_for_updates(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Quick check: fetch remote + compare HEAD with last indexed SHA."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    from app.api.deps import validate_safe_id

    validate_safe_id(project_id, "project_id")
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
        db,
        project_id,
        branch=project.repo_branch,
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


async def _fetch_live_table_names(
    db: AsyncSession,
    project_id: str,
) -> list[str] | None:
    """Best-effort: introspect the first active connection's table names."""
    try:
        from app.connectors.registry import get_connector

        connections = await _connection_svc.list_by_project(db, project_id)
        for conn in connections:
            if not conn.is_active:
                continue
            cfg = await _connection_svc.to_config(db, conn)
            connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
            await connector.connect(cfg)
            try:
                schema = await connector.introspect_schema()
                return [t.name for t in schema.tables]
            finally:
                await connector.disconnect()
    except Exception:
        logger.debug("Could not fetch live table names for cross-reference", exc_info=True)
    return None


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


# -----------------------------------------------------------------------
# Multi-Repository Management
# -----------------------------------------------------------------------


class AddRepoRequest(BaseModel):
    name: str = Field(max_length=200)
    repo_url: str = Field(max_length=2000)
    branch: str = Field("main", max_length=200)
    provider: Literal["git_ssh", "git_https", "github", "gitlab", "bitbucket"] = "git_ssh"
    ssh_key_id: str | None = Field(None, max_length=64)


class RepoResponse(BaseModel):
    id: str
    project_id: str
    name: str
    provider: str
    repo_url: str
    branch: str
    ssh_key_id: str | None = None
    indexing_status: str = "idle"
    last_indexed_commit: str | None = None


@router.post("/{project_id}/repositories", response_model=RepoResponse, status_code=201)
@limiter.limit("10/minute")
async def add_repository(
    request: Request,
    project_id: str,
    body: AddRepoRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Add a new repository to a project."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    project = await _project_svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo = await _repo_svc.create(
        db,
        project_id=project_id,
        name=body.name,
        repo_url=body.repo_url,
        branch=body.branch,
        provider=body.provider,
        ssh_key_id=body.ssh_key_id,
    )
    audit_log(
        "repo.create",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="repository",
        resource_id=repo.id,
    )
    return repo


@router.get("/{project_id}/repositories", response_model=list[RepoResponse])
async def list_repositories(
    project_id: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all repositories for a project."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    repos = await _repo_svc.list_by_project(db, project_id)
    return repos[:limit]


class UpdateRepoRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    branch: str | None = Field(None, max_length=200)
    ssh_key_id: str | None = Field(None, max_length=64)


@router.patch("/repositories/{repo_id}", response_model=RepoResponse)
@limiter.limit("10/minute")
async def update_repository(
    request: Request,
    repo_id: str,
    body: UpdateRepoRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update an existing repository."""
    repo = await _repo_svc.get(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    await _membership_svc.require_role(db, repo.project_id, user["user_id"], "editor")

    update_data = body.model_dump(exclude_unset=True)
    updated = await _repo_svc.update(db, repo_id, **update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Repository not found")
    audit_log(
        "repo.update",
        user_id=user["user_id"],
        project_id=repo.project_id,
        resource_type="repository",
        resource_id=repo_id,
    )
    return updated


@router.delete("/repositories/{repo_id}")
@limiter.limit("10/minute")
async def delete_repository(
    request: Request,
    repo_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove a repository from a project."""
    repo = await _repo_svc.get(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    await _membership_svc.require_role(db, repo.project_id, user["user_id"], "owner")

    deleted = await _repo_svc.delete(db, repo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repository not found")
    audit_log(
        "repo.delete",
        user_id=user["user_id"],
        project_id=repo.project_id,
        resource_type="repository",
        resource_id=repo_id,
    )
    return {"ok": True}
