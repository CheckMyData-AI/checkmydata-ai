"""Audit fixes for the auto-investigation background path.

Two related findings are pinned here:

FINDING 1 (budget & concurrency bypass)
  ``_run_investigation_background`` previously built a bare ``LLMRouter()`` with
  no ``usage_sink`` and acquired no ``agent_limiter`` slot, so an
  InvestigationAgent (up to 12 LLM iterations) ran entirely off the books — a
  user at/over budget still incurred unbilled, unbounded background LLM spend
  and many suspicious results could spawn uncapped concurrent agents. The fix:

  * the router carries a ``DbUsageSink`` bound to the originating user,
  * an ``agent_limiter`` slot is acquired before the run and released after,
  * ``maybe_auto_investigate`` preflights the owner's token budget and skips
    spawning the investigation entirely when the budget is already exhausted.

FINDING 2 (verdict dead-ends)
  On success the runner only wrote ``corrected_query``/``root_cause`` to the
  ``DataInvestigation`` row; the diagnosis was never surfaced. The fix emits a
  durable, user-scoped ``Notification`` linking the finding back to the
  originating ``trigger_message_id``.

All LLM/agent work is mocked — no network, no real model calls.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import chat_feedback as fb_module
from app.api.routes import data_investigations as di_module
from app.config import settings
from app.models.base import Base


@pytest_asyncio.fixture
async def engine_and_sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, sm
    await engine.dispose()


async def _seed_owner_project_connection(sm) -> tuple[str, str, str]:
    """Create a User (owner), a Project owned by them, and a Connection.

    Returns (user_id, project_id, connection_id). The owner is what the
    system-driven auto-investigation attributes LLM spend / notifications to,
    mirroring the owner-attribution used by the code↔DB sync pipeline.
    """
    from app.models.connection import Connection
    from app.models.project import Project
    from app.models.user import User

    user_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    connection_id = str(uuid.uuid4())
    async with sm() as s:
        s.add(User(id=user_id, email=f"owner-{user_id[:8]}@test.com", password_hash="x"))
        s.add(Project(id=project_id, name="proj", owner_id=user_id))
        s.add(
            Connection(
                id=connection_id,
                project_id=project_id,
                name="conn",
                db_type="postgres",
                db_host="localhost",
                db_port=5432,
                db_name="test",
                db_user="user",
                db_password_encrypted="enc",
            )
        )
        await s.commit()
    return user_id, project_id, connection_id


def _suspicious_result():
    return SimpleNamespace(
        error=None,
        suspicious_result=True,
        suspicious_reason="validation failed",
        query="SELECT * FROM orders",
        results=SimpleNamespace(row_count=0, error=None),
    )


def _stub_to_config(monkeypatch):
    """Bypass credential decryption — the seeded Connection carries a dummy
    encrypted blob, and these tests exercise the agent/sink/limiter wiring, not
    real connection config."""

    async def _fake(_self, _session, _conn):
        return SimpleNamespace(connection_id=getattr(_conn, "id", None))

    monkeypatch.setattr(
        "app.services.connection_service.ConnectionService.to_config",
        _fake,
        raising=False,
    )


# ---------------------------------------------------------------------------
# FINDING 1 — budget preflight in maybe_auto_investigate
# ---------------------------------------------------------------------------


class TestAutoInvestigateBudgetPreflight:
    @pytest.mark.asyncio
    async def test_skips_when_owner_budget_exhausted(self, engine_and_sm, monkeypatch):
        """When the project owner's token budget is exhausted, the suspicious
        result must NOT create an investigation row nor schedule any background
        task — the auto-investigation is skipped entirely (no unbilled LLM
        spend)."""
        import asyncio

        _, sm = engine_and_sm
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        _user, project_id, connection_id = await _seed_owner_project_connection(sm)

        # Owner is over budget.
        async def _over_budget(_self, _session, _user_id):
            return "Daily token budget exceeded — upgrade your plan."

        monkeypatch.setattr(
            "app.services.usage_service.UsageService.check_token_budget",
            _over_budget,
            raising=False,
        )

        # A recording fake: prove create_investigation is NEVER reached when
        # the budget is exhausted (rather than relying on an exception trap,
        # which the broad best-effort except would mask).
        calls: list[str] = []

        class _RecordingSvc:
            async def create_investigation(self, _session, **kwargs):
                calls.append("create_investigation")
                return SimpleNamespace(id="inv-should-not-exist")

        monkeypatch.setattr(
            "app.services.investigation_service.InvestigationService",
            lambda: _RecordingSvc(),
            raising=False,
        )

        scheduled: list[str] = []
        real_create_task = asyncio.create_task

        async def _noop():
            return None

        def _capture(coro, *a, **k):
            name = getattr(coro, "__qualname__", getattr(coro, "__name__", str(coro)))
            if "_run_investigation_background" in str(name):
                scheduled.append(str(name))
                if hasattr(coro, "close"):
                    coro.close()
                return real_create_task(_noop())
            return real_create_task(coro, *a, **k)

        monkeypatch.setattr(asyncio, "create_task", _capture)

        await fb_module.maybe_auto_investigate(
            _suspicious_result(),
            project_id=project_id,
            connection_id=connection_id,
            session_id="s1",
            message_id="m1",
        )

        assert calls == [], "no investigation row should be created when over budget"
        assert scheduled == [], "no background task should be scheduled when over budget"

    @pytest.mark.asyncio
    async def test_spawns_with_owner_user_id_when_in_budget(self, engine_and_sm, monkeypatch):
        """In-budget: the background runner is scheduled and receives the
        resolved owner ``user_id`` plus the originating ``trigger_message_id``
        so it can sink usage and surface the verdict to the right user."""
        import asyncio

        _, sm = engine_and_sm
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        owner_id, project_id, connection_id = await _seed_owner_project_connection(sm)

        async def _in_budget(_self, _session, _user_id):
            return None

        monkeypatch.setattr(
            "app.services.usage_service.UsageService.check_token_budget",
            _in_budget,
            raising=False,
        )

        class _FakeSvc:
            async def create_investigation(self, _session, **kwargs):
                return SimpleNamespace(id="inv-1")

        monkeypatch.setattr(
            "app.services.investigation_service.InvestigationService",
            lambda: _FakeSvc(),
            raising=False,
        )

        launched: dict[str, object] = {}

        async def _fake_bg(**kwargs):
            launched.update(kwargs)

        monkeypatch.setattr(
            "app.api.routes.data_investigations._run_investigation_background",
            _fake_bg,
            raising=False,
        )

        tasks: list[asyncio.Task] = []
        real_create_task = asyncio.create_task

        def _capture(coro, *a, **k):
            t = real_create_task(coro, *a, **k)
            tasks.append(t)
            return t

        monkeypatch.setattr(asyncio, "create_task", _capture)

        await fb_module.maybe_auto_investigate(
            _suspicious_result(),
            project_id=project_id,
            connection_id=connection_id,
            session_id="s1",
            message_id="m-trigger",
        )

        assert tasks, "background investigation task must be scheduled when in budget"
        await asyncio.gather(*tasks)
        assert launched.get("user_id") == owner_id
        assert launched.get("trigger_message_id") == "m-trigger"


# ---------------------------------------------------------------------------
# FINDING 1 — sink + limiter inside _run_investigation_background
# ---------------------------------------------------------------------------


class TestAutoInvestigateBudgetEnforcementFlag:
    """B8: auto_investigate_budget_enforcement_enabled gates the budget guard."""

    @pytest.mark.asyncio
    async def test_skips_when_owner_unresolved_and_enforcement_on(self, engine_and_sm, monkeypatch):
        """Enforcement on (default) + owner cannot be resolved → skip entirely
        (no unbilled, unattributed background spend)."""
        import asyncio

        _, sm = engine_and_sm
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        monkeypatch.setattr(
            settings, "auto_investigate_budget_enforcement_enabled", True, raising=False
        )
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        _user, project_id, connection_id = await _seed_owner_project_connection(sm)

        async def _no_owner(_session, _project_id):
            return None

        monkeypatch.setattr(
            "app.services.sync_budget.resolve_owner_user_id", _no_owner, raising=False
        )

        calls: list[str] = []

        class _RecordingSvc:
            async def create_investigation(self, _session, **kwargs):
                calls.append("create_investigation")
                return SimpleNamespace(id="should-not-exist")

        monkeypatch.setattr(
            "app.services.investigation_service.InvestigationService",
            lambda: _RecordingSvc(),
            raising=False,
        )

        scheduled: list[str] = []
        real_create_task = asyncio.create_task

        async def _noop():
            return None

        def _capture(coro, *a, **k):
            name = getattr(coro, "__qualname__", getattr(coro, "__name__", str(coro)))
            if "_run_investigation_background" in str(name):
                scheduled.append(str(name))
                if hasattr(coro, "close"):
                    coro.close()
                return real_create_task(_noop())
            return real_create_task(coro, *a, **k)

        monkeypatch.setattr(asyncio, "create_task", _capture)

        await fb_module.maybe_auto_investigate(
            _suspicious_result(),
            project_id=project_id,
            connection_id=connection_id,
            session_id="s1",
            message_id="m1",
        )

        assert calls == [], "owner unresolved + enforcement on must not create an investigation"
        assert scheduled == [], "owner unresolved + enforcement on must not schedule a task"

    @pytest.mark.asyncio
    async def test_proceeds_when_enforcement_disabled_even_over_budget(
        self, engine_and_sm, monkeypatch
    ):
        """Enforcement off → the budget guard is bypassed; the investigation is
        scheduled even when the owner is over budget."""
        import asyncio

        _, sm = engine_and_sm
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        monkeypatch.setattr(
            settings, "auto_investigate_budget_enforcement_enabled", False, raising=False
        )
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        _owner, project_id, connection_id = await _seed_owner_project_connection(sm)

        async def _over_budget(_self, _session, _user_id):
            return "Daily token budget exceeded."

        monkeypatch.setattr(
            "app.services.usage_service.UsageService.check_token_budget",
            _over_budget,
            raising=False,
        )

        class _FakeSvc:
            async def create_investigation(self, _session, **kwargs):
                return SimpleNamespace(id="inv-1")

        monkeypatch.setattr(
            "app.services.investigation_service.InvestigationService",
            lambda: _FakeSvc(),
            raising=False,
        )

        launched: dict[str, object] = {}

        async def _fake_bg(**kwargs):
            launched.update(kwargs)

        monkeypatch.setattr(
            "app.api.routes.data_investigations._run_investigation_background",
            _fake_bg,
            raising=False,
        )

        tasks: list[asyncio.Task] = []
        real_create_task = asyncio.create_task

        def _capture(coro, *a, **k):
            t = real_create_task(coro, *a, **k)
            tasks.append(t)
            return t

        monkeypatch.setattr(asyncio, "create_task", _capture)

        await fb_module.maybe_auto_investigate(
            _suspicious_result(),
            project_id=project_id,
            connection_id=connection_id,
            session_id="s1",
            message_id="m1",
        )

        assert tasks, "investigation must be scheduled when budget enforcement is disabled"
        await asyncio.gather(*tasks)


class TestRunInvestigationBackgroundSinkAndLimiter:
    @pytest.mark.asyncio
    async def test_router_carries_sink_and_limiter_acquired(self, engine_and_sm, monkeypatch):
        """The router handed to the InvestigationAgent must carry a non-null
        usage sink bound to the user, and an agent_limiter slot must be
        acquired and released around the run."""
        _, sm = engine_and_sm
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        owner_id, project_id, connection_id = await _seed_owner_project_connection(sm)
        _stub_to_config(monkeypatch)

        from app.llm.usage_sink import NullUsageSink

        captured: dict[str, object] = {}

        # Capture the router/ctx the agent receives.
        class _FakeAgent:
            async def run(self, ctx, **kwargs):
                captured["sink"] = ctx.llm_router._sink
                captured["limiter_held"] = acquired and not released
                return SimpleNamespace(
                    status="failed",
                    corrected_query=None,
                    corrected_result=None,
                    root_cause="no fix",
                    root_cause_category=None,
                )

        monkeypatch.setattr(
            "app.agents.investigation_agent.InvestigationAgent",
            lambda: _FakeAgent(),
            raising=False,
        )

        acquired = False
        released = False
        real_acquire = di_module.agent_limiter.acquire
        real_release = di_module.agent_limiter.release

        async def _acquire(user_id):
            nonlocal acquired
            acquired = True
            captured["acquire_user"] = user_id
            return await real_acquire(user_id)

        async def _release(user_id):
            nonlocal released
            released = True
            captured["release_user"] = user_id
            return await real_release(user_id)

        monkeypatch.setattr(di_module.agent_limiter, "acquire", _acquire, raising=False)
        monkeypatch.setattr(di_module.agent_limiter, "release", _release, raising=False)

        await di_module._run_investigation_background(
            investigation_id="inv-x",
            project_id=project_id,
            connection_id=connection_id,
            original_query="SELECT 1",
            original_result_summary="{}",
            user_complaint_type="auto_suspicious",
            user_complaint_detail="bad",
            user_expected_value="",
            problematic_column="",
            user_id=owner_id,
            trigger_message_id="m1",
            session_id="s1",
        )

        assert captured.get("sink") is not None
        assert not isinstance(captured["sink"], NullUsageSink), (
            "router must carry a DbUsageSink, not the no-op NullUsageSink"
        )
        assert acquired, "agent_limiter slot must be acquired"
        assert released, "agent_limiter slot must be released"
        assert captured.get("acquire_user") == owner_id
        assert captured.get("release_user") == owner_id

    @pytest.mark.asyncio
    async def test_limiter_released_even_on_agent_crash(self, engine_and_sm, monkeypatch):
        """A crash mid-investigation must not leak the concurrency slot."""
        _, sm = engine_and_sm
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        owner_id, project_id, connection_id = await _seed_owner_project_connection(sm)
        _stub_to_config(monkeypatch)

        class _BoomAgent:
            async def run(self, ctx, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            "app.agents.investigation_agent.InvestigationAgent",
            lambda: _BoomAgent(),
            raising=False,
        )

        released = False
        real_release = di_module.agent_limiter.release

        async def _release(user_id):
            nonlocal released
            released = True
            return await real_release(user_id)

        monkeypatch.setattr(di_module.agent_limiter, "release", _release, raising=False)

        # Must not raise (best-effort) and must release the slot.
        await di_module._run_investigation_background(
            investigation_id="inv-x",
            project_id=project_id,
            connection_id=connection_id,
            original_query="SELECT 1",
            original_result_summary="{}",
            user_complaint_type="auto_suspicious",
            user_complaint_detail="bad",
            user_expected_value="",
            problematic_column="",
            user_id=owner_id,
            trigger_message_id="m1",
            session_id="s1",
        )

        assert released, "agent_limiter slot must be released even when the agent crashes"


# ---------------------------------------------------------------------------
# FINDING 2 — verdict surfacing as a durable, user-scoped Notification
# ---------------------------------------------------------------------------


class TestVerdictSurfacing:
    @pytest.mark.asyncio
    async def test_success_emits_notification_tied_to_trigger_message(
        self, engine_and_sm, monkeypatch
    ):
        """A successful investigation must emit a durable Notification for the
        owner, linking the finding to the originating trigger_message_id."""
        from sqlalchemy import select

        from app.models.notification import Notification

        _, sm = engine_and_sm
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        owner_id, project_id, connection_id = await _seed_owner_project_connection(sm)
        _stub_to_config(monkeypatch)

        class _FixAgent:
            async def run(self, ctx, **kwargs):
                return SimpleNamespace(
                    status="success",
                    corrected_query="SELECT * FROM orders WHERE deleted_at IS NULL",
                    corrected_result={"rows": [[5]]},
                    root_cause="Soft-deleted rows were not filtered out.",
                    root_cause_category="missing_filter",
                )

        monkeypatch.setattr(
            "app.agents.investigation_agent.InvestigationAgent",
            lambda: _FixAgent(),
            raising=False,
        )

        await di_module._run_investigation_background(
            investigation_id="inv-done",
            project_id=project_id,
            connection_id=connection_id,
            original_query="SELECT * FROM orders",
            original_result_summary="{}",
            user_complaint_type="auto_suspicious",
            user_complaint_detail="numbers too high",
            user_expected_value="",
            problematic_column="",
            user_id=owner_id,
            trigger_message_id="m-origin",
            session_id="s1",
        )

        async with sm() as s:
            rows = (
                (await s.execute(select(Notification).where(Notification.user_id == owner_id)))
                .scalars()
                .all()
            )

        assert len(rows) == 1, "exactly one verdict notification should be emitted"
        notif = rows[0]
        assert notif.project_id == project_id
        # The notification must link back to the originating message so it is
        # not discoverable only by opening the investigations table.
        assert "m-origin" in (notif.body or ""), "notification must reference trigger_message_id"
        assert "inv-done" in (notif.body or ""), "notification must reference the investigation"
        assert "Soft-deleted" in (notif.body or ""), "notification must surface the root cause"

    @pytest.mark.asyncio
    async def test_no_fix_does_not_emit_notification(self, engine_and_sm, monkeypatch):
        """When no fix is found, no verdict notification is emitted (the row
        is simply marked failed)."""
        from sqlalchemy import select

        from app.models.notification import Notification

        _, sm = engine_and_sm
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)
        owner_id, project_id, connection_id = await _seed_owner_project_connection(sm)
        _stub_to_config(monkeypatch)

        class _NoFixAgent:
            async def run(self, ctx, **kwargs):
                return SimpleNamespace(
                    status="failed",
                    corrected_query=None,
                    corrected_result=None,
                    root_cause="Could not determine a fix.",
                    root_cause_category=None,
                )

        monkeypatch.setattr(
            "app.agents.investigation_agent.InvestigationAgent",
            lambda: _NoFixAgent(),
            raising=False,
        )

        await di_module._run_investigation_background(
            investigation_id="inv-nofix",
            project_id=project_id,
            connection_id=connection_id,
            original_query="SELECT 1",
            original_result_summary="{}",
            user_complaint_type="auto_suspicious",
            user_complaint_detail="bad",
            user_expected_value="",
            problematic_column="",
            user_id=owner_id,
            trigger_message_id="m-origin",
            session_id="s1",
        )

        async with sm() as s:
            rows = (
                (await s.execute(select(Notification).where(Notification.user_id == owner_id)))
                .scalars()
                .all()
            )

        assert rows == [], "no notification when the agent finds no fix"
