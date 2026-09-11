"""A chat session with no owner belonged to everybody (AUTH-02/03, audit 2026-09-09).

`chat_sessions.user_id` is `ondelete="SET NULL"`, and the migration that added it
(`d8a2f4b19c73`) added it **nullable with no backfill** — so ownerless rows are not
hypothetical, they are the normal residue of an account deletion and of every session
created before that migration.

Three places then read a NULL owner as "yours":

- `_require_session_owner` (`chat_sessions.py:133`) guards with
  ``if session_obj.user_id and session_obj.user_id != user_id`` — a falsy owner
  short-circuits the comparison, so **any authenticated user** could read, rename, retitle
  or delete the session, without belonging to its project or even to the tenant.
- `ChatService.list_sessions` and the `ensure_welcome` count **union** `user_id IS NULL`
  into a user-scoped query — an affirmative widening, not an oversight.
- `validate_session_access`, which `POST /api/chat/ask` and `/ask/stream` use to decide
  whether a caller may continue a session, repeats the falsy short-circuit.

The codebase already refuses this exact union by name for its other two owner-scoped
stores: `ssh_key_service.py:71-76` and `vendor_credential_service.py:158-165` both say a
NULL-owner row must not be unioned in, "that would show one user's vendor key to every
other user". Sessions carry the questions, the generated SQL, sample rows and every turn's
metadata.

**Decision D-TENANCY-1: a NULL owner means orphaned, not public.** There is no way to
recover whose it was, and inventing an owner would assert something false, so such a row
becomes unreachable rather than shared. Measured on production before shipping: 28
sessions, **0 ownerless**, so this changes no live access — the tightening is for the
deployments where an account has been deleted.

**And BIZ-04:** deleting an account left its sessions in *other people's* projects behind,
where the `SET NULL` then widened who could read them. Own projects cascade; foreign ones
did not. The handler's own docstring promises "permanently delete the current user and all
associated data".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chat_service import ChatService


def _session(**kw):
    base = dict(id="s1", project_id="p1", user_id="u1")
    base.update(kw)
    return SimpleNamespace(**base)


class TestValidateSessionAccess:
    """The gate `POST /api/chat/ask` consults before continuing an existing session."""

    @pytest.mark.asyncio
    async def test_an_ownerless_session_is_not_everyones(self) -> None:
        svc = ChatService()
        with patch.object(svc, "get_session", AsyncMock(return_value=_session(user_id=None))):
            got = await svc.validate_session_access(AsyncMock(), "s1", "p1", "u2")
        assert got is None, (
            "a session whose owner was set to NULL by an account deletion was handed to "
            "the next caller who asked for it"
        )

    @pytest.mark.asyncio
    async def test_another_users_session_is_still_refused(self) -> None:
        svc = ChatService()
        with patch.object(svc, "get_session", AsyncMock(return_value=_session(user_id="u1"))):
            assert await svc.validate_session_access(AsyncMock(), "s1", "p1", "u2") is None

    @pytest.mark.asyncio
    async def test_the_owner_still_gets_their_own_session(self) -> None:
        svc = ChatService()
        with patch.object(svc, "get_session", AsyncMock(return_value=_session(user_id="u1"))):
            assert await svc.validate_session_access(AsyncMock(), "s1", "p1", "u1") is not None

    @pytest.mark.asyncio
    async def test_a_session_from_another_project_is_refused(self) -> None:
        svc = ChatService()
        with patch.object(svc, "get_session", AsyncMock(return_value=_session(project_id="pX"))):
            assert await svc.validate_session_access(AsyncMock(), "s1", "p1", "u1") is None


class TestTheListDoesNotUnionOwnerlessRows:
    """The delivery mechanism: the list is where a co-member learns the session ids.

    Checked by compiling the statement the query actually builds, not by reading the source.
    The first draft of these two grepped for `is_(None)` and went red against the comment
    explaining why the union was removed — the same shape the 2026-09-09 audit files as
    TEST-04, met for the third time in this programme.
    """

    @staticmethod
    async def _statements(coro_factory) -> list[str]:
        """Every SQL statement a call compiles, as text."""
        seen: list[str] = []

        class _Result:
            def scalars(self):
                return self

            def all(self):
                return []

            def scalar_one(self):
                return 0

            def scalar_one_or_none(self):
                return None

        async def execute(stmt, *a, **kw):
            seen.append(str(stmt))
            return _Result()

        db = AsyncMock()
        db.execute = execute
        await coro_factory(db)
        return seen

    @pytest.mark.asyncio
    async def test_list_sessions_does_not_widen_on_null_owner(self) -> None:
        svc = ChatService()
        stmts = await self._statements(
            lambda db: svc.list_sessions(db, "p1", user_id="u1"),
        )
        assert stmts, "no statement was compiled — the test is not exercising the query"
        for sql in stmts:
            assert "IS NULL" not in sql.upper(), (
                "list_sessions unions ownerless rows into a user-scoped query — the exact "
                f"widening ssh_key_service refuses by name: {sql}"
            )

    @pytest.mark.asyncio
    async def test_the_welcome_count_does_not_widen_either(self) -> None:
        svc = ChatService()
        stmts = await self._statements(
            lambda db: svc.ensure_welcome_session(db, "p1", "u1"),
        )
        for sql in stmts:
            assert "USER_ID IS NULL" not in sql.upper(), (
                f"ensure_welcome counts other people's ownerless rows: {sql}"
            )


class TestAccountDeletionTakesTheSessionsWithIt:
    """BIZ-04. Own projects cascade; sessions in someone else's project did not."""

    def test_the_handler_deletes_chat_sessions_by_user(self) -> None:
        import ast
        import pathlib

        route = pathlib.Path(__file__).parents[2] / "app" / "api" / "routes" / "auth.py"
        tree = ast.parse(route.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "delete_account"
        )
        deleted = {
            a.id
            for call in ast.walk(fn)
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "delete"
            for a in call.args
            if isinstance(a, ast.Name)
        }
        assert "ChatSession" in deleted, (
            "delete_account does not delete the user's chat sessions, so the ones in other "
            "people's projects survive with user_id NULL — readable by everyone (BIZ-04)"
        )
