"""A role is a value with a domain, and three places took one without saying so.

* **F-PROJ-07** — `ROLE_HIERARCHY.get(min_role, 0)` gives an unknown *required* role a
  rank of **0**, which every real member outranks. So a typo in the required role does
  not deny access, it grants it to everyone including viewers: fail-**open**. Measured
  across `app/`: 143 literal `require_role` call sites, all three literals valid today
  (`viewer` 76, `owner` 46, `editor` 21) — so this is latent, and what makes it latent
  is 143 bare strings being right rather than anything checking them.

  The mirror case fails closed but silently: a *stored* role outside the domain ranks 0
  too, so a member with a corrupt role is denied everything with no trace of why.

* **F-PROJ-11** — `add_member` reads, then inserts, with a `UniqueConstraint` on
  `(project_id, user_id)` and no `IntegrityError` guard. Two concurrent accepts of the
  same invite both see no row, both insert, and one gets a 500.

* **F-PROJ-08** — `InviteCreate.role` advertises `owner` and the route answers 400. The
  schema is what a client generates against, so it promises something the endpoint
  refuses. Ownership has one entrance by design (F-PROJ-10's transfer route, which
  enforces the receiving owner's quota); the invite schema should say so rather than
  offer a second door that slams.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.project  # noqa: F401
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
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
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


class TestAnUnknownRequiredRoleDoesNotOpenTheDoor:
    @pytest.mark.asyncio
    async def test_a_typo_in_the_required_role_is_refused_not_ranked_zero(self, db):
        """The sharp half of F-PROJ-07: rank 0 for an unknown `min_role` means every
        member outranks it, so `require_role(..., "Owner")` would admit viewers."""
        u = await _user(db)
        p = await _project(db)
        await svc.add_member(db, p.id, u.id, "viewer")

        from app.services.membership_service import UnknownRoleError

        with pytest.raises(UnknownRoleError) as exc:
            await svc.require_role(db, p.id, u.id, "Owner")
        # Not merely "something raised": direct indexing into ROLE_HIERARCHY would also
        # raise, with `KeyError: 'Owner'` — loud but useless to whoever reads the log.
        # The explicit check earns its place on the message, so the message is asserted.
        msg = str(exc.value)
        assert "Owner" in msg and "not a known role" in msg, msg
        assert "editor" in msg and "owner" in msg and "viewer" in msg, (
            f"the error should name the domain it expected: {msg}"
        )

    @pytest.mark.asyncio
    async def test_a_valid_required_role_still_works(self, db):
        u = await _user(db)
        p = await _project(db)
        await svc.add_member(db, p.id, u.id, "editor")
        assert await svc.require_role(db, p.id, u.id, "viewer") == "editor"
        with pytest.raises(HTTPException) as exc:
            await svc.require_role(db, p.id, u.id, "owner")
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_a_corrupt_stored_role_denies_access_and_says_why(self, db, caplog):
        """The mirror case fails closed, but a silent lockout has no trace to follow."""
        import logging

        u = await _user(db)
        p = await _project(db)
        member = await svc.add_member(db, p.id, u.id, "viewer")
        member.role = "editer"  # a typo that predates validation
        await db.commit()

        with caplog.at_level(logging.WARNING, logger="app.services.membership_service"):
            with pytest.raises(HTTPException) as exc:
                await svc.require_role(db, p.id, u.id, "viewer")
        assert exc.value.status_code == 403
        assert [r for r in caplog.records if r.levelno >= logging.WARNING], (
            "a member denied because their stored role is unrecognised must leave a trace"
        )


class TestAddMemberGuardsItsDomain:
    @pytest.mark.asyncio
    async def test_an_unknown_role_cannot_be_stored(self, db):
        u = await _user(db)
        p = await _project(db)
        with pytest.raises(ValueError, match="role"):
            await svc.add_member(db, p.id, u.id, "editer")

    @pytest.mark.asyncio
    async def test_every_hierarchy_role_is_accepted(self, db):
        """`owner` included: project creation and the demo path both pass it."""
        p = await _project(db)
        for role in ("owner", "editor", "viewer"):
            u = await _user(db)
            m = await svc.add_member(db, p.id, u.id, role)
            assert m.role == role

    @pytest.mark.asyncio
    async def test_a_concurrent_duplicate_add_returns_the_row_not_a_500(self, tmp_path):
        """F-PROJ-11: read-then-insert against a UNIQUE constraint.

        Faithful to what the loser of the race actually sees: its read misses, and by
        the time it commits the winner's row exists. Simulated by having the first
        commit fail *and* the row appear — through a second session on a file-backed
        database, since two sessions on `:memory:` cannot see each other.

        An earlier version of this test patched `AsyncSession.execute` and produced a
        `MissingGreenlet` instead of the race — the simulation has to happen at the
        transaction boundary, not inside the driver.
        """
        from sqlalchemy.exc import IntegrityError

        url = f"sqlite+aiosqlite:///{tmp_path / 'race.db'}"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_factory() as setup:
            u = await _user(setup)
            p = await _project(setup)
            uid, pid = u.id, p.id

        async with session_factory() as loser:
            real_commit = loser.commit
            state = {"raised": False}

            async def commit_once():
                if not state["raised"]:
                    state["raised"] = True
                    # The winner lands its row, then our INSERT violates the constraint.
                    async with session_factory() as winner:
                        winner.add(
                            __import__(
                                "app.models.project_member", fromlist=["ProjectMember"]
                            ).ProjectMember(project_id=pid, user_id=uid, role="viewer")
                        )
                        await winner.commit()
                    raise IntegrityError("UNIQUE constraint failed", None, Exception())
                await real_commit()

            loser.commit = commit_once  # type: ignore[method-assign]
            member = await svc.add_member(loser, pid, uid, "editor")

        assert state["raised"], "the race branch was never exercised"
        assert member is not None
        assert member.user_id == uid
        assert member.role == "editor", "the caller's intent must survive the retry"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_a_constraint_failure_that_is_not_the_race_surfaces_as_itself(self, db):
        """The `member is None` branch decides *which* error the caller sees.

        Without the re-raise the code hits `None.role` and reports an AttributeError —
        loud, but pointing at this function instead of at the constraint that actually
        fired. A misattributed error costs the next reader the same investigation twice.
        """
        from sqlalchemy.exc import IntegrityError

        u = await _user(db)
        p = await _project(db)
        real_commit = db.commit

        async def always_conflict():
            raise IntegrityError("UNIQUE constraint failed", None, Exception())

        db.commit = always_conflict  # type: ignore[method-assign]
        try:
            with pytest.raises(IntegrityError):
                await svc.add_member(db, p.id, u.id, "viewer")
        finally:
            db.commit = real_commit  # type: ignore[method-assign]


class TestInviteSchemaTellsTheTruth:
    def test_owner_is_not_offered_by_the_invite_schema(self):
        import pydantic

        from app.api.routes.invites import InviteCreate

        with pytest.raises(pydantic.ValidationError):
            InviteCreate(email="a@b.com", role="owner")

    def test_the_invitable_roles_are_defined_once(self):
        """`RoleUpdate` and `InviteCreate` must not drift: ownership has one entrance
        (the transfer route, which enforces the receiving owner's plan quota) and two
        schemas offering it independently is how that stops being true."""
        from app.api.routes.invites import InviteCreate, RoleUpdate

        def _allowed(model):
            import typing

            return set(typing.get_args(model.model_fields["role"].annotation))

        assert _allowed(InviteCreate) == _allowed(RoleUpdate) == {"editor", "viewer"}
