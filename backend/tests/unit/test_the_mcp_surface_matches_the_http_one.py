"""Six places the MCP and access-control surface drifted from the rules it shares.

P2 row 20; AUTH-04, AUTH-05, AUTH-06, AUTH-07, AUTH-08 and BIZ-07.

- **AUTH-04** — every MCP agent call acquires the shared concurrency/quota slot
  **twice**: once at dispatch (`limited=True`) and once inside the tool body.
  `AgentLimiter.acquire` is a counter, not a re-entrant lock. Both comments claim to
  be adding the gate for the first time, in two places, so the doubling was invisible
  to each author — and an MCP client is cut off after 50 calls against a configured
  ceiling of 100, with a message naming a limit it has not reached.
- **AUTH-05** — one process-wide git-webhook secret authorises re-indexing of *any*
  project id in *any* tenant. The signature proves "someone holds the deployment's
  secret", never "someone controls this project's repository", and the endpoint also
  enumerates which project ids exist and have a repository.
- **AUTH-06** — MCP `execute_raw_query` hands the raw connector exception to the
  client, bypassing the scrubber every sibling path uses.
- **AUTH-07** — `get_accessible_projects` is a third, **member-only** reader of an
  access rule whose own docstring calls itself the single source of truth and states
  it as *owns OR is a member of*. An owner whose member row is missing — which
  project creation's two separate commits can produce — is refused by this reader and
  admitted by the other four.
- **AUTH-08** — `update_member_role` writes the role without validating it. The
  F-PROJ-07 guard was applied to `add_member` and not to the second writer, and a
  stored typo ranks 0: it locks the member out of everything.
- **BIZ-07** — `execute_raw_query` is the one query path that writes no audit row,
  against an invariant that says every answer is traceable.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest


class TestOneCallTakesOneSlot:
    """AUTH-04."""

    def test_the_slot_is_acquired_in_exactly_one_layer(self) -> None:
        """Paired per tool, because one layer is right and two is the defect.

        `execute_raw_query` has no internal acquire and legitimately keeps
        `limited=True`; the first draft forbade `limited=True` anywhere alongside any
        tool-body acquire, which would have made that site wrong too.
        """
        from app.mcp_server import server as server_mod
        from app.mcp_server import tools as tools_mod

        acquiring_tools = {
            node.name
            for node in ast.walk(ast.parse(inspect.getsource(tools_mod)))
            if isinstance(node, ast.AsyncFunctionDef)
            and "agent_limiter.acquire" in ast.unparse(node)
        }
        assert acquiring_tools, "no tool acquires a slot at all; this guard is blind"

        doubled: list[str] = []
        for call in ast.walk(ast.parse(inspect.getsource(server_mod))):
            if not isinstance(call, ast.Call) or "_with_principal" not in ast.unparse(call.func):
                continue
            limited = any(
                kw.arg == "limited"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in call.keywords
            )
            if not limited:
                continue
            dispatched = ast.unparse(call.args[0]) if call.args else ""
            doubled += [name for name in acquiring_tools if f"tools.{name}(" in dispatched]

        assert not doubled, (
            f"{doubled} are gated at BOTH the dispatch and inside the tool. "
            "`AgentLimiter.acquire` is a counter, not a re-entrant lock — it "
            "increments `_concurrent` AND appends to the hourly window on every call. "
            "Two parallel MCP queries therefore take three of three slots and the "
            "second is refused with a message naming a limit it has not reached, and "
            "the same client is cut off after 50 calls against a configured ceiling "
            "of 100 (AUTH-04)"
        )


class TestAWebhookProvesControlOfItsOwnProject:
    """AUTH-05."""

    def test_the_secret_is_bound_to_the_project(self) -> None:
        from app.api.routes import repos as repos_mod

        source = textwrap.dedent(inspect.getsource(repos_mod.repo_webhook))
        assert "webhook_secret" in source and "settings.git_webhook_secret" not in source, (
            "the body is HMACed against one process-wide secret and nothing binds it "
            "to the {project_id} in the path — so the signature proves 'someone holds "
            "the deployment's secret', never 'someone controls this project's "
            "repository'. Every tenant who wires a webhook is given the same string, "
            "and can then drive any other tenant's memory-constrained worker into "
            "`generate_docs` on demand (AUTH-05)"
        )

    def test_each_project_gets_its_own(self) -> None:
        from app.models.repository import ProjectRepository

        assert "webhook_secret_encrypted" in ProjectRepository.__table__.c, (
            "there is nowhere to store a per-project secret, so there cannot be one"
        )

    def test_an_unknown_project_and_a_bad_signature_look_alike(self) -> None:
        """The endpoint enumerated which project ids exist and have a repository.

        A 404 for an unknown id, a different 404 for an unindexed one and a 401 for a
        bad signature are three distinguishable answers to an unauthenticated caller.
        """
        from app.api.routes import repos as repos_mod

        source = textwrap.dedent(inspect.getsource(repos_mod.repo_webhook))
        tree = ast.parse(source.replace("async def", "def", 1))
        # The DETAIL, not the status. A 404 for "webhook ingestion disabled" is a
        # deployment-wide fact and enumerates nothing; the first draft banned every
        # 404 in the handler and would have rejected that one too.
        leaks = [
            ast.unparse(kw.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and "HTTPException" in ast.unparse(node.func)
            for kw in node.keywords
            if kw.arg == "detail" and "not found" in ast.unparse(kw.value).lower()
        ]
        assert not leaks, (
            f"the handler still tells an unauthenticated caller which project ids "
            f"exist and which have a repository: {leaks}. All of those are 'this "
            "request is not authorised for this project' to somebody who cannot prove "
            "otherwise (AUTH-05)"
        )


class TestTheMcpClientSeesAScrubbedError:
    """AUTH-06."""

    def test_the_raw_connector_exception_is_not_forwarded(self) -> None:
        from app.mcp_server import tools as tools_mod

        source = textwrap.dedent(inspect.getsource(tools_mod.execute_raw_query))
        assert "safe_error" in source, (
            "the raw connector exception reaches the MCP client, bypassing the "
            "scrubber every sibling path uses — the DB branch of `connection_service` "
            "already wraps its own (AUTH-06)"
        )


class TestOneAccessRuleHasOneReader:
    """AUTH-07."""

    def test_accessible_projects_uses_the_shared_filter(self) -> None:
        from app.services.membership_service import MembershipService

        source = textwrap.dedent(inspect.getsource(MembershipService.get_accessible_projects))
        assert "_accessible_filter" in source, (
            "`_accessible_filter`'s own docstring calls itself the single source of "
            "truth and states the rule as 'owns OR is a member of'. This reader joins "
            "ProjectMember and nothing else, so an owner whose member row is missing "
            "— which project creation's two separate commits can produce — is refused "
            "here and admitted by the other four readers (AUTH-07)"
        )

    @pytest.mark.asyncio
    async def test_an_owner_without_a_member_row_is_still_accessible(self) -> None:
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.models.base import Base
        from app.models.project import Project
        from app.models.user import User
        from app.services.membership_service import MembershipService

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        owner_id = uuid.uuid4().hex
        async with sm() as session:
            session.add(User(id=owner_id, email="o@example.com", password_hash="x"))
            session.add(Project(id=uuid.uuid4().hex, name="orphaned", owner_id=owner_id))
            await session.commit()

            projects = await MembershipService().get_accessible_projects(session, owner_id)
        await engine.dispose()

        assert [p.name for p in projects] == ["orphaned"], (
            "the person named on the project cannot see it, while `can_access` admits "
            "them — the two readers disagree about the same rule (AUTH-07)"
        )


class TestARoleIsValidatedByBothWriters:
    """AUTH-08."""

    @pytest.mark.asyncio
    async def test_an_invalid_role_is_refused_on_update(self) -> None:
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.models.base import Base
        from app.models.project import Project
        from app.models.project_member import ProjectMember
        from app.models.user import User
        from app.services.membership_service import MembershipService

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        project_id, member_id = uuid.uuid4().hex, uuid.uuid4().hex
        async with sm() as session:
            session.add(User(id=member_id, email="m@example.com", password_hash="x"))
            session.add(Project(id=project_id, name="p"))
            session.add(ProjectMember(project_id=project_id, user_id=member_id, role="viewer"))
            await session.commit()

            with pytest.raises(Exception) as caught:
                await MembershipService().update_member_role(
                    session, project_id, member_id, "editorr"
                )
        await engine.dispose()

        assert "editorr" in str(caught.value) or "role" in str(caught.value).lower(), (
            "the F-PROJ-07 guard was applied to `add_member` and not to the second "
            "writer, and a stored typo ranks 0 — it locks the member out of "
            f"everything. Raised: {caught.value!r} (AUTH-08)"
        )


class TestEveryQueryPathIsTraceable:
    """BIZ-07."""

    def test_execute_raw_query_writes_an_audit_row(self) -> None:
        """On the path that SUCCEEDS.

        The first draft asked only that `audit_log` appear somewhere in the function
        — and the failure branch calls it too, so deleting the success-path row left
        the guard green and every completed raw query untraceable.
        """
        from app.mcp_server import tools as tools_mod

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(tools_mod.execute_raw_query)).replace(
                "async def", "def", 1
            )
        )
        handlers = {
            id(node)
            for handler in ast.walk(tree)
            if isinstance(handler, ast.ExceptHandler)
            for node in ast.walk(handler)
        }
        on_success = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and "audit_log" in ast.unparse(node.func)
            and id(node) not in handlers
        ]
        assert on_success, (
            "this is the one query path that writes no audit row, against an invariant "
            "that says every answer is traceable — and it is the path that runs "
            "caller-supplied SQL (BIZ-07)"
        )
