import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

router = APIRouter()
_project_svc = ProjectService()
_conn_svc = ConnectionService()
_membership_svc = MembershipService()
_rule_svc = RuleService()


@router.post("/setup")
@limiter.limit("3/minute")
async def demo_setup(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a demo project with an in-memory SQLite connection and seed tables."""
    user_id = user["user_id"]

    project = await _project_svc.create(
        db,
        name="Demo Project",
        description="Auto-generated demo project with sample data",
        owner_id=user_id,
    )
    await _membership_svc.add_member(db, project.id, user_id, "owner")
    await _rule_svc.ensure_default_rule(db, project.id)

    conn = await _conn_svc.create(
        db,
        project_id=project.id,
        name="Demo SQLite",
        db_type="sqlite",
        db_host="",
        db_port=0,
        db_name=":memory:",
        db_user="",
        db_password="",
        is_read_only=False,
    )

    await db.commit()
    await db.refresh(project)
    await db.refresh(conn)

    logger.info(
        "Demo setup complete: project=%s connection=%s user=%s",
        project.id[:8],
        conn.id[:8],
        user_id[:8],
    )

    return {"project_id": project.id, "connection_id": conn.id}
