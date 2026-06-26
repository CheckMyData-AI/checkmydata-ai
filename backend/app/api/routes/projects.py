import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.background import spawn_tracked
from app.core.datetime_utils import ensure_aware
from app.core.rate_limit import limiter
from app.knowledge.repo_url import validate_git_ref, validate_repo_url
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.email_service import EmailService
from app.services.knowledge_catalog_service import KnowledgeCatalogService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rule_service import RuleService
from app.services.sync_budget import preflight_owner_budget

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ProjectService()
_membership_svc = MembershipService()
_rule_svc = RuleService()
_conn_svc = ConnectionService()
_db_index_svc = DbIndexService()
_sync_svc = CodeDbSyncService()
_email_svc = EmailService()
_catalog_svc = KnowledgeCatalogService()


class AccessRequestBody(BaseModel):
    email: str = Field(max_length=255)
    description: str = Field(max_length=500)
    message: str = Field(max_length=2000)


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

    @field_validator("repo_url")
    @classmethod
    def _validate_repo_url(cls, v: str | None) -> str | None:
        return validate_repo_url(v) if v else v

    @field_validator("repo_branch")
    @classmethod
    def _validate_repo_branch(cls, v: str | None) -> str | None:
        return validate_git_ref(v) if v else v


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("repo_url")
    @classmethod
    def _validate_repo_url(cls, v: str | None) -> str | None:
        return validate_repo_url(v) if v else v

    @field_validator("repo_branch")
    @classmethod
    def _validate_repo_branch(cls, v: str | None) -> str | None:
        return validate_git_ref(v) if v else v

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
    from app.models.user import User

    user_obj = (
        await db.execute(select(User).where(User.id == user["user_id"]))
    ).scalar_one_or_none()
    if not user_obj or not user_obj.can_create_projects:
        raise HTTPException(
            status_code=403,
            detail="You are not eligible to create projects. Please request access.",
        )

    # T-BILL-2: plan-based paywall on project count (402 + upgrade payload).
    from app.services.entitlement_service import EntitlementService, QuotaExceededError

    try:
        await EntitlementService().enforce_project_quota(db, user["user_id"])
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=exc.as_payload()) from exc

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


@router.post("/access-requests")
@limiter.limit("3/hour")
async def request_project_access(
    request: Request,
    body: AccessRequestBody,
    user: dict = Depends(get_current_user),
):
    """Submit a request to be granted project creation privileges."""
    await _email_svc.send_access_request_email(
        requester_email=body.email,
        description=body.description,
        message=body.message,
        user_id=user["user_id"],
    )
    audit_log(
        "project.access_request",
        user_id=user["user_id"],
        detail=body.email,
    )
    return {"ok": True}


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
    # T17: fetch all roles in one query instead of N+1.
    roles = await _membership_svc.get_roles_bulk(db, [p.id for p in projects], user["user_id"])
    result = []
    for p in projects:
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
                user_role=roles.get(p.id),
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
@limiter.limit("20/minute")
async def update_project(
    request: Request,
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    project = await _svc.update(db, project_id, **body.model_dump(exclude_unset=True))
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
        user_role="owner",
    )


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
                age = datetime.now(UTC) - ensure_aware(record.created_at)
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


@router.get("/{project_id}/knowledge-health")
async def project_knowledge_health(
    project_id: str,
    connection_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Knowledge Health panel data: actionable freshness + artifact counts.

    Phase 1 (Knowledge Catalog). Read-only facade over the existing stores via
    :class:`KnowledgeCatalogService`. ``connection_id`` is optional — when omitted
    the first connection on the project is used so the panel works right after a
    DB is added. The returned ``freshness.warnings`` carry a structured
    ``recommended_action`` the UI renders as one-click re-index/re-sync buttons
    that hit the consolidated ``task_queue`` execution path.
    """
    from pathlib import Path

    from app.config import settings

    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Resolve the connection to evaluate: explicit query param wins; otherwise
    # fall back to the first connection on the project (mirrors readiness).
    resolved_conn_id = connection_id
    if resolved_conn_id is None:
        connections = await _conn_svc.list_by_project(db, project_id)
        if connections:
            resolved_conn_id = connections[0].id

    repo_clone_dir = Path(settings.repo_clone_base_dir) / project_id

    return await _catalog_svc.get_knowledge_health(
        db,
        project_id=project_id,
        connection_id=resolved_conn_id,
        repo_clone_dir=repo_clone_dir,
    )


@router.get("/{project_id}/sync-history")
async def project_sync_history(
    project_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Recent scheduled daily-sync runs for a project (viewer access).

    Sourced from ``indexing_runs`` (kind=daily_sync); ordered newest-first.
    """
    from app.services.sync_history_service import SyncHistoryService

    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    limit = max(1, min(limit, 50))
    runs = await SyncHistoryService().list_for_project(db, project_id, limit=limit)
    return {"runs": runs}


class SyncScheduleBody(BaseModel):
    enabled: bool | None = None
    hour: int | None = Field(default=None, ge=0, le=23)


@router.get("/{project_id}/sync-schedule")
async def get_sync_schedule(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Effective daily-sync schedule for a project (project override → global)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.services.daily_knowledge_sync_service import compute_next_scheduled_run
    from app.services.sync_schedule_service import SyncScheduleService

    eff = await SyncScheduleService().effective(db, project_id)
    next_run = None
    if eff["enabled"]:
        tz = eff["timezone"]
        next_run = compute_next_scheduled_run(
            datetime.now(ZoneInfo(tz)), hour=eff["hour"], timezone_name=tz
        ).isoformat()
    return {**eff, "next_run": next_run}


@router.put("/{project_id}/sync-schedule")
@limiter.limit("20/minute")
async def put_sync_schedule(
    request: Request,
    project_id: str,
    body: SyncScheduleBody,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Set a per-project daily-sync override (editor)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")
    from app.services.sync_schedule_service import SyncScheduleService

    try:
        return await SyncScheduleService().set_override(
            db, project_id, enabled=body.enabled, hour=body.hour
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/sync-now", status_code=202)
@limiter.limit("5/minute")
async def sync_now(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger a daily-sync run on demand (editor)."""
    import uuid

    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")

    # C3: budget pre-flight — block over-budget owners before we even acquire the lock.
    ok, reason, _ = await preflight_owner_budget(db, project_id)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)

    from app.core import task_queue
    from app.services.run_coordinator import RunAlreadyActiveError, RunCoordinator

    coord = RunCoordinator()
    try:
        run = await coord.start(
            db, kind="daily_sync", project_id=project_id, connection_id=None, trigger="manual"
        )
    except RunAlreadyActiveError:
        active = await coord._find_active(db, project_id, "daily_sync", None)
        if active is None:
            raise HTTPException(status_code=409, detail="Daily sync already in progress") from None
        return {"run_id": active.id, "workflow_id": active.workflow_id, "status": "running"}

    if task_queue.is_arq_active():
        await task_queue.enqueue(
            "run_daily_project_knowledge_sync",
            task_id=f"daily_sync_manual:{project_id}:{uuid.uuid4().hex[:8]}",
            project_id=project_id,
        )
    else:
        from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService

        spawn_tracked(
            DailyKnowledgeSyncService().run_for_project(project_id, trigger="manual"),
            name=f"daily_sync:{project_id}",
        )
    return {"run_id": run.id, "workflow_id": run.workflow_id, "status": "started"}


@router.get("/{project_id}/runs")
async def project_runs(
    project_id: str,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Background-run history for a project (viewer access)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    from app.services.logs_service import LogsService

    limit = max(1, min(limit, 200))
    return await LogsService().list_runs(db, project_id, kind=kind, status=status, limit=limit)


@router.get("/{project_id}/pipeline-status")
async def project_pipeline_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Unified repo index / DB index / code-DB sync status for all project members."""
    from app.api.routes import connections as conn_routes
    from app.api.routes import repos as repo_routes
    from app.services.pipeline_status_service import PipelineStatusService

    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    project = await _svc.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_task = repo_routes._indexing_tasks.get(project_id)
    in_memory_repo = repo_task is not None and not repo_task.done()

    in_memory_db: dict[str, bool] = {}
    for cid, task in conn_routes._db_index_tasks.items():
        if not task.done():
            in_memory_db[cid] = True

    in_memory_sync: dict[str, bool] = {}
    for cid, task in conn_routes._sync_tasks.items():
        if not task.done():
            in_memory_sync[cid] = True

    svc = PipelineStatusService()
    return await svc.get_status(
        db,
        project_id,
        in_memory_repo_indexing=in_memory_repo,
        in_memory_db_index=in_memory_db,
        in_memory_sync=in_memory_sync,
    )
