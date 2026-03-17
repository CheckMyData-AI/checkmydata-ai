import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ProjectService()
_membership_svc = MembershipService()
_rule_svc = RuleService()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    repo_url: str | None = None
    repo_branch: str = "main"
    ssh_key_id: str | None = None
    indexing_llm_provider: str | None = None
    indexing_llm_model: str | None = None
    agent_llm_provider: str | None = None
    agent_llm_model: str | None = None
    sql_llm_provider: str | None = None
    sql_llm_model: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    description: str | None = None
    repo_url: str | None = None
    repo_branch: str | None = None
    ssh_key_id: str | None = None
    indexing_llm_provider: str | None = None
    indexing_llm_model: str | None = None
    agent_llm_provider: str | None = None
    agent_llm_model: str | None = None
    sql_llm_provider: str | None = None
    sql_llm_model: str | None = None


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
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    data = body.model_dump()
    data["owner_id"] = user["user_id"]
    project = await _svc.create(db, **data)
    await _membership_svc.add_member(db, project.id, user["user_id"], "owner")
    await _rule_svc.ensure_default_rule(db, project.id)
    await db.commit()
    await db.refresh(project)
    logger.info(
        "Project created: name=%s id=%s owner=%s",
        body.name, project.id[:8], user["user_id"][:8],
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
async def delete_project(
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
    return {"ok": True}
