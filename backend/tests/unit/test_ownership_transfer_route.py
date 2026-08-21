"""Route-level contract for POST /{project_id}/transfer-ownership (F-PROJ-10).

The finding is that an owner's departure stranded a workspace, and the hard case is
an *orphaned* project: `Project.owner_id` is `ondelete="SET NULL"`, so a deleted
account leaves a project nobody owns and nobody can appoint an owner for. The route
therefore must NOT gate on `require_role(..., "owner")` — that check 403s everyone on
exactly the project the feature exists to rescue.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

import app.api.routes.invites as inv


def _request() -> Request:
    # A real Request, minimally scoped: the route carries `@limiter.limit` and slowapi
    # rejects anything that is not a starlette Request.
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/projects/p1/transfer-ownership",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "app": SimpleNamespace(state=SimpleNamespace(limiter=None)),
        }
    )


async def _call(user: dict) -> tuple[object, dict]:
    seen: dict = {}

    async def _transfer(db, project_id, **kwargs):  # noqa: ARG001
        seen.update({"project_id": project_id, **kwargs})

    with patch.object(inv._membership_svc, "transfer_ownership", AsyncMock(side_effect=_transfer)):
        resp = await inv.transfer_ownership(
            request=_request(),
            project_id="p1",
            body=inv.OwnershipTransfer(new_owner_user_id="u-new"),
            db=AsyncMock(),
            user=user,
        )
    return resp, seen


@pytest.mark.asyncio
async def test_the_route_does_not_pre_gate_on_owner_role():
    """`require_role` must not be what decides: it would 403 on an orphaned project.

    A plant that added `await _membership_svc.require_role(db, ..., "owner")` back to
    the route would leave every service test green while re-stranding exactly the
    workspace the feature is for, so the assertion is on the route's own behaviour.
    """
    with patch.object(inv._membership_svc, "require_role", AsyncMock()) as gate:
        _, seen = await _call({"user_id": "u-old", "email": "old@x.com"})
    gate.assert_not_awaited()
    assert seen["new_owner_user_id"] == "u-new"


@pytest.mark.asyncio
async def test_the_actor_and_their_admin_status_reach_the_service():
    """The service cannot decide the orphan case without knowing both."""
    _, seen = await _call({"user_id": "u-old", "email": "old@x.com"})
    assert seen["actor_user_id"] == "u-old"
    assert seen["actor_is_admin"] is False


@pytest.mark.asyncio
async def test_an_admin_email_is_forwarded_as_admin():
    from app.config import settings

    # `settings` is a pydantic model — instance attributes are frozen, so the patch
    # goes on the class.
    with patch.object(type(settings), "is_admin_email", lambda _self, e: e == "boss@x.com"):
        _, seen = await _call({"user_id": "u-boss", "email": "boss@x.com"})
    assert seen["actor_is_admin"] is True


@pytest.mark.asyncio
async def test_a_successful_transfer_returns_204_with_no_body():
    resp, _ = await _call({"user_id": "u-old", "email": "old@x.com"})
    assert resp.status_code == 204
    assert not resp.body


@pytest.mark.asyncio
async def test_owner_is_not_an_assignable_role_on_the_role_route():
    """Ownership must have exactly one path in, or the quota check has a bypass."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        inv.RoleUpdate(role="owner")
