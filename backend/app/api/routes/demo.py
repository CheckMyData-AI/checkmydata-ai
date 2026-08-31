"""The demo project — a first-run user's first look at what the product does.

Four board findings lived here, and the one that mattered most was a promise. SCN-003
says the demo path "sets up sample data" and the button offers to *load demo data*; the
route seeded nothing and pointed at `:memory:`, which is empty on every fresh connection
anyway. So the first thing a new user saw after clicking "Try demo instead" was an empty
database, and the reasonable conclusion is that the product does not work.

The other three were quieter: no quota check on either the project or the connection
(F-BILL-07), a connection created writable against the read-only default (F-EXP-02), and
no dedup, so every call minted another Demo Project against quotas the user was not being
charged for (F-EXP-03).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.entitlements import QuotaExceededError, get_entitlements
from app.models.connection import Connection
from app.models.project import Project
from app.services.connection_service import ConnectionService
from app.services.demo_data import DEMO_PROJECT_NAME, demo_db_path, seed_demo_db
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
    """Create (or reuse) the demo project, with a seeded sample database behind it."""
    user_id = user["user_id"]

    # F-EXP-03: reuse rather than multiply. Three calls a minute are allowed by the rate
    # limit, and each used to leave a project and a connection behind.
    existing = (
        await db.execute(
            select(Project).where(
                Project.owner_id == user_id,
                Project.name == DEMO_PROJECT_NAME,
            )
        )
    ).scalar_one_or_none()

    db_path = demo_db_path(user_id)
    # Re-seed unconditionally: the file may be gone (ephemeral disk) even when the
    # project row survived, and `seed_demo_db` returns early when the rows are there.
    # `ConnectionService.to_config` repairs it later too, for the dyno restart that
    # happens between this call and the user's first question.
    seed_demo_db(db_path)

    if existing is not None:
        conn = (
            await db.execute(
                select(Connection).where(Connection.project_id == existing.id).limit(1)
            )
        ).scalar_one_or_none()
        if conn is not None:
            logger.info("Demo setup: reusing project=%s for user=%s", existing.id[:8], user_id[:8])
            return {"project_id": existing.id, "connection_id": conn.id}

    # F-BILL-07: the demo is a project and a connection like any other, so it meets the
    # same plan. Bypassing the gate here made the paywall optional for anyone who found
    # this route.
    try:
        await get_entitlements().enforce_project_quota(db, user_id)
        await get_entitlements().enforce_connection_quota(db, user_id)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=exc.as_payload()) from exc

    project = existing or await _project_svc.create(
        db,
        name=DEMO_PROJECT_NAME,
        description="Sample project with a small customers/orders dataset",
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
        db_name=str(db_path),
        db_user="",
        db_password="",
        # F-EXP-02: read-only, like every other connection unless someone says otherwise.
        # A demo is the last place to make an exception to the product's own default.
        is_read_only=True,
    )

    await db.commit()
    await db.refresh(project)
    await db.refresh(conn)

    logger.info(
        "Demo setup complete: project=%s connection=%s user=%s db=%s",
        project.id[:8],
        conn.id[:8],
        user_id[:8],
        db_path.name,
    )

    return {"project_id": project.id, "connection_id": conn.id}
