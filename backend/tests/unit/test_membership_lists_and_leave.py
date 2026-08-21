"""F-PROJ-13 (unbounded lists) and F-PROJ-12 (no way to leave a project).

**F-PROJ-13.** `list_members` and `list_invites` were bare `SELECT` by project, and
the members one adds `selectinload(user)` on top. Nothing bounded either. Invites in
particular accumulate — pending and expired rows are never pruned — so the list grows
with time rather than with the team.

The cap is the easy half. The half that matters is not lying about it: a members list
that quietly shows 500 of 5,000 is the same shape as a truncated query result reported
as a total, and this session has been unpicking that shape all day. So the route
publishes the real total in a header and logs when the cap bites, and the number the
caller sees is never presented as complete when it is not.

**F-PROJ-12.** There was no way for a member to remove themselves; only an owner could
remove them. Leaving is coherent *now* specifically because F-PROJ-10 made ownership
transferable: an owner still cannot walk out — that would strand the workspace, which
is the finding F-PROJ-10 fixed — but they can hand it over first and then leave.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.project  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.models.user import User
from app.services.membership_service import MembershipService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user(db) -> User:
    u = User(email=f"u-{uuid.uuid4().hex[:8]}@t.com", password_hash="x", display_name="T")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _project(db) -> Project:
    p = Project(name=f"p-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


svc = MembershipService()


class TestMemberListIsBounded:
    @pytest.mark.asyncio
    async def test_the_list_stops_at_the_limit(self, db):
        p = await _project(db)
        for _ in range(12):
            await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        assert len(await svc.list_members(db, p.id, limit=5)) == 5

    @pytest.mark.asyncio
    async def test_the_total_is_available_separately(self, db):
        """The cap must not become the number anyone reports as the team size."""
        p = await _project(db)
        for _ in range(12):
            await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        assert await svc.count_members(db, p.id) == 12
        assert len(await svc.list_members(db, p.id, limit=5)) == 5

    @pytest.mark.asyncio
    async def test_a_nonpositive_limit_is_refused_rather_than_meaning_unlimited(self, db):
        """`limit=0` reading as "no limit" is how a cap becomes decorative."""
        p = await _project(db)
        await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        for bad in (0, -1):
            with pytest.raises(ValueError):
                await svc.list_members(db, p.id, limit=bad)

    @pytest.mark.asyncio
    async def test_an_absurd_limit_is_clamped_not_honoured(self, db, monkeypatch):
        """Observed by shrinking the maximum rather than growing the table.

        A first version asked for 10 million against a single member and asserted one
        row came back — true whether or not the clamp exists, so it proved nothing. The
        clamp is only visible when it actually binds.
        """
        from app.services import membership_service as mod

        monkeypatch.setattr(mod, "MAX_MEMBER_PAGE", 3)
        p = await _project(db)
        for _ in range(5):
            await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        rows = await svc.list_members(db, p.id, limit=10_000_000)
        assert len(rows) == 3, f"a caller cannot lift the ceiling by asking: {len(rows)}"

    @pytest.mark.asyncio
    async def test_an_ordinary_limit_below_the_maximum_is_honoured(self, db):
        p = await _project(db)
        for _ in range(5):
            await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        assert len(await svc.list_members(db, p.id, limit=4)) == 4

    @pytest.mark.asyncio
    async def test_hitting_the_cap_is_logged(self, db, caplog):
        import logging

        p = await _project(db)
        for _ in range(4):
            await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        with caplog.at_level(logging.WARNING, logger="app.services.membership_service"):
            await svc.list_members(db, p.id, limit=2)
        assert [r for r in caplog.records if r.levelno >= logging.WARNING], (
            "a capped list that nobody is told about is a partial answer presented as a whole one"
        )

    @pytest.mark.asyncio
    async def test_a_list_inside_the_cap_says_nothing(self, db, caplog):
        import logging

        p = await _project(db)
        await svc.add_member(db, p.id, (await _user(db)).id, "viewer")
        with caplog.at_level(logging.WARNING, logger="app.services.membership_service"):
            await svc.list_members(db, p.id, limit=50)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestLeaveProject:
    @pytest.mark.asyncio
    async def test_a_member_can_remove_themselves(self, db):
        p = await _project(db)
        owner, member = await _user(db), await _user(db)
        p.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, p.id, owner.id, "owner")
        await svc.add_member(db, p.id, member.id, "editor")

        assert await svc.leave_project(db, p.id, member.id) is True
        assert await svc.get_role(db, p.id, member.id) is None

    @pytest.mark.asyncio
    async def test_the_owner_cannot_walk_out_and_strand_the_workspace(self, db):
        """The exact failure F-PROJ-10 exists to prevent — so leaving must refuse it,
        and the message must point at the thing that now makes it possible."""
        p = await _project(db)
        owner = await _user(db)
        p.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, p.id, owner.id, "owner")

        with pytest.raises(HTTPException) as exc:
            await svc.leave_project(db, p.id, owner.id)
        assert exc.value.status_code == 400
        assert "transfer" in exc.value.detail.lower(), exc.value.detail

    @pytest.mark.asyncio
    async def test_leaving_a_project_you_are_not_in_is_not_a_success(self, db):
        p = await _project(db)
        stranger = await _user(db)
        assert await svc.leave_project(db, p.id, stranger.id) is False

    @pytest.mark.asyncio
    async def test_leaving_is_idempotent(self, db):
        p = await _project(db)
        owner, member = await _user(db), await _user(db)
        p.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, p.id, owner.id, "owner")
        await svc.add_member(db, p.id, member.id, "viewer")
        assert await svc.leave_project(db, p.id, member.id) is True
        assert await svc.leave_project(db, p.id, member.id) is False

    @pytest.mark.asyncio
    async def test_an_owner_by_column_only_is_still_refused(self, db):
        """Ownership reads from `Project.owner_id` OR a member row; both must block."""
        p = await _project(db)
        owner = await _user(db)
        p.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, p.id, owner.id, "editor")  # row disagrees with column

        with pytest.raises(HTTPException):
            await svc.leave_project(db, p.id, owner.id)


class TestRoutesTellTheTruthAboutTheList:
    @staticmethod
    def _request(path: str = "/api/invites/p1/members/me"):
        from types import SimpleNamespace

        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "method": "DELETE",
                "path": path,
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "app": SimpleNamespace(state=SimpleNamespace(limiter=None)),
            }
        )

    @pytest.mark.asyncio
    async def test_a_capped_page_is_marked_as_capped(self):
        from unittest.mock import AsyncMock, patch

        from starlette.responses import Response as StarletteResponse

        import app.api.routes.invites as inv

        resp = StarletteResponse()
        with (
            patch.object(inv._membership_svc, "require_role", AsyncMock(return_value="viewer")),
            patch.object(inv._membership_svc, "list_members", AsyncMock(return_value=[])),
            patch.object(inv._membership_svc, "count_members", AsyncMock(return_value=1234)),
        ):
            await inv.list_members(
                project_id="p1", response=resp, db=AsyncMock(), user={"user_id": "u"}
            )
        assert resp.headers["X-Total-Count"] == "1234"
        assert resp.headers["X-Result-Capped"] == "true", (
            "a page shorter than the total must say so, or the body reads as complete"
        )

    @pytest.mark.asyncio
    async def test_a_complete_page_is_marked_complete(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from starlette.responses import Response as StarletteResponse

        import app.api.routes.invites as inv

        resp = StarletteResponse()
        member = MagicMock(
            id="m",
            project_id="p1",
            user_id="u",
            role="viewer",
            user=MagicMock(email="a@b.c", display_name="A"),
        )
        with (
            patch.object(inv._membership_svc, "require_role", AsyncMock(return_value="viewer")),
            patch.object(inv._membership_svc, "list_members", AsyncMock(return_value=[member])),
            patch.object(inv._membership_svc, "count_members", AsyncMock(return_value=1)),
        ):
            await inv.list_members(
                project_id="p1", response=resp, db=AsyncMock(), user={"user_id": "u"}
            )
        assert resp.headers["X-Result-Capped"] == "false"

    @pytest.mark.asyncio
    async def test_leaving_returns_204_with_no_body(self):
        from unittest.mock import AsyncMock, patch

        import app.api.routes.invites as inv

        with patch.object(inv._membership_svc, "leave_project", AsyncMock(return_value=True)):
            out = await inv.leave_project(
                request=self._request(), project_id="p1", db=AsyncMock(), user={"user_id": "u"}
            )
        assert out.status_code == 204 and not out.body

    @pytest.mark.asyncio
    async def test_leaving_a_project_you_are_not_in_is_a_404(self):
        from unittest.mock import AsyncMock, patch

        import app.api.routes.invites as inv

        with patch.object(inv._membership_svc, "leave_project", AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc:
                await inv.leave_project(
                    request=self._request(), project_id="p1", db=AsyncMock(), user={"user_id": "u"}
                )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_the_route_acts_only_on_the_caller(self):
        """`/members/me` means no request can even express "remove someone else"."""
        from unittest.mock import AsyncMock, patch

        import app.api.routes.invites as inv

        seen = {}

        async def _leave(db, project_id, user_id):  # noqa: ARG001
            seen["user_id"] = user_id
            return True

        with patch.object(inv._membership_svc, "leave_project", AsyncMock(side_effect=_leave)):
            await inv.leave_project(
                request=self._request(), project_id="p1", db=AsyncMock(), user={"user_id": "caller"}
            )
        assert seen["user_id"] == "caller"
