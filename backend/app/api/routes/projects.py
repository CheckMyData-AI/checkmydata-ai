import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ProjectService()
_membership_svc = MembershipService()
_rule_svc = RuleService()
_conn_svc = ConnectionService()
_db_index_svc = DbIndexService()
_sync_svc = CodeDbSyncService()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    repo_url: str | None = Field(default=None, max_length=1000)
    repo_branch: str = Field(default="main", max_length=255)
    ssh_key_id: str | None = None
    indexing_llm_provider: str | None = Field(default=None, max_length=100)
    indexing_llm_model: str | None = Field(default=None, max_length=200)
    agent_llm_provider: str | None = Field(default=None, max_length=100)
    agent_llm_model: str | None = Field(default=None, max_length=200)
    sql_llm_provider: str | None = Field(default=None, max_length=100)
    sql_llm_model: str | None = Field(default=None, max_length=200)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    description: str | None = Field(None, max_length=2000)
    repo_url: str | None = Field(None, max_length=1024)
    repo_branch: str | None = Field(None, max_length=255)
    ssh_key_id: str | None = Field(None, max_length=255)
    indexing_llm_provider: str | None = Field(None, max_length=100)
    indexing_llm_model: str | None = Field(None, max_length=100)
    agent_llm_provider: str | None = Field(None, max_length=100)
    agent_llm_model: str | None = Field(None, max_length=100)
    sql_llm_provider: str | None = Field(None, max_length=100)
    sql_llm_model: str | None = Field(None, max_length=100)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    repo_url: str | None
    repo_branch: str
    ssh_key_id: str | None
    indexing_llm_provider: str | None = None
    indexing_llm_model: str | None = None
    agent_llm_provider: str | None = None
    agent_llm_model: str | None = None
    sql_llm_provider: str | None = None
    sql_llm_model: str | None = None
    owner_id: str | None = None
    user_role: str | None = None


@router.post("", response_model=ProjectResponse)
@limiter.limit("10/minute")
async def create_project(
    request: Request,
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from sqlalchemy import and_, select

    from app.models.project import Project

    data = body.model_dump()
    data["owner_id"] = user["user_id"]

    existing = await db.execute(
        select(Project).where(
            and_(
                Project.owner_id == user["user_id"],
                Project.name == body.name,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists",
        )

    project = await _svc.create(db, **data)
    await _membership_svc.add_member(db, project.id, user["user_id"], "owner")
    await _rule_svc.ensure_default_rule(db, project.id)
    await db.commit()
    await db.refresh(project)
    logger.info(
        "Project created: name=%s id=%s owner=%s",
        body.name,
        project.id[:8],
        user["user_id"][:8],
    )
    audit_log(
        "project.create",
        user_id=user["user_id"],
        project_id=project.id,
        resource_type="project",
    )
    return ProjectResponse(
        **{k: getattr(project, k) for k in ProjectResponse.model_fields if k not in ("user_role",)},
        user_role="owner",
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
    result = []
    for p in projects:
        role = await _membership_svc.get_role(db, p.id, user["user_id"])
        result.append(
            ProjectResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                repo_url=p.repo_url,
                repo_branch=p.repo_branch,
                ssh_key_id=p.ssh_key_id,
                indexing_llm_provider=p.indexing_llm_provider,
                indexing_llm_model=p.indexing_llm_model,
                agent_llm_provider=p.agent_llm_provider,
                agent_llm_model=p.agent_llm_model,
                sql_llm_provider=p.sql_llm_provider,
                sql_llm_model=p.sql_llm_model,
                owner_id=p.owner_id,
                user_role=role,
            )
        )
    return result


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    role = await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        repo_url=project.repo_url,
        repo_branch=project.repo_branch,
        ssh_key_id=project.ssh_key_id,
        indexing_llm_provider=project.indexing_llm_provider,
        indexing_llm_model=project.indexing_llm_model,
        agent_llm_provider=project.agent_llm_provider,
        agent_llm_model=project.agent_llm_model,
        sql_llm_provider=project.sql_llm_provider,
        sql_llm_model=project.sql_llm_model,
        owner_id=project.owner_id,
        user_role=role,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    project = await _svc.update(db, project_id, **body.model_dump(exclude_unset=True))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
@limiter.limit("5/minute")
async def delete_project(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    logger.info("Project delete requested: id=%s", project_id[:8])
    try:
        deleted = await _svc.delete(db, project_id)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Project still has dependent resources that prevent deletion",
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    audit_log(
        "project.delete",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="project",
    )
    return {"ok": True}


@router.get("/{project_id}/readiness")
async def project_readiness(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Check project readiness for chat: repo, DB, index, and sync status."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from app.config import settings
    from app.knowledge.git_tracker import GitTracker
    from app.knowledge.repo_analyzer import RepoAnalyzer

    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_connected = bool(project.repo_url)

    repo_indexed = False
    last_indexed_at = None
    commits_behind = 0
    is_stale = False

    if repo_connected:
        git_tracker = GitTracker()
        repo_analyzer = RepoAnalyzer(settings.repo_clone_base_dir)
        try:
            record = await git_tracker.get_last_indexed_record(
                db,
                project_id,
                branch=project.repo_branch,
            )
            repo_indexed = record is not None
            if record and record.created_at:
                last_indexed_at = record.created_at.isoformat()
                age = datetime.now(UTC) - record.created_at.replace(tzinfo=UTC)
                repo_dir = repo_analyzer.get_repo_dir(project_id)
                if repo_dir.exists() and record.commit_sha:
                    try:
                        head_sha = await asyncio.to_thread(
                            git_tracker.get_head_sha,
                            repo_dir,
                        )
                        if head_sha != record.commit_sha:
                            commits_behind = await git_tracker.count_commits_ahead(
                                repo_dir,
                                record.commit_sha,
                            )
                    except Exception:
                        logger.debug("Readiness: git head check failed", exc_info=True)
                is_stale = age > timedelta(days=7) and commits_behind > 0
        except Exception:
            logger.warning("Readiness: repo index check failed", exc_info=True)

    connections = await _conn_svc.list_by_project(db, project_id)
    db_connected = len(connections) > 0

    db_indexed = False
    code_db_synced = False
    active_connection_id = None

    for conn in connections:
        active_connection_id = conn.id
        indexed = await _db_index_svc.is_indexed(db, conn.id)
        if indexed:
            db_indexed = True
            synced = await _sync_svc.is_synced(db, conn.id)
            if synced:
                code_db_synced = True
            break

    missing_steps = []
    if not repo_connected:
        missing_steps.append({"step": "connect_repo", "label": "Connect a Git repository"})
    if not repo_indexed:
        missing_steps.append({"step": "index_repo", "label": "Index the repository"})
    if not db_connected:
        missing_steps.append({"step": "connect_db", "label": "Add a database connection"})
    if not db_indexed:
        missing_steps.append({"step": "index_db", "label": "Index the database"})
    if not code_db_synced:
        missing_steps.append({"step": "sync", "label": "Run Code-DB Sync"})

    ready = repo_connected and repo_indexed and db_connected and db_indexed and code_db_synced

    return {
        "repo_connected": repo_connected,
        "repo_indexed": repo_indexed,
        "db_connected": db_connected,
        "db_indexed": db_indexed,
        "code_db_synced": code_db_synced,
        "ready": ready,
        "missing_steps": missing_steps,
        "active_connection_id": active_connection_id,
        "last_indexed_at": last_indexed_at,
        "commits_behind": commits_behind,
        "is_stale": is_stale,
    }
