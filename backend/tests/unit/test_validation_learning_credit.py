"""R4-2: a *validated, successful* result must credit its exposed learnings as
applied (bump ``times_applied``) automatically — without waiting for a rare
thumbs-up — so the decay/ranking signal stays live in production. Errors and
the disable flag must suppress the credit."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import chat as chat_module
from app.config import settings
from app.models.agent_learning import AgentLearning
from app.models.base import Base


@pytest_asyncio.fixture
async def engine_and_sm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, sm
    await engine.dispose()


async def _seed(sm, connection_id: str, *, times_applied: int = 0) -> str:
    lrn = AgentLearning(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        category="schema_gotcha",
        subject="users",
        lesson=f"Lesson {uuid.uuid4().hex[:6]}",
        lesson_hash=uuid.uuid4().hex[:32],
        confidence=0.8,
        times_applied=times_applied,
        is_active=True,
    )
    async with sm() as s:
        s.add(lrn)
        await s.commit()
    return lrn.id


async def _seed_message(sm, *, exposed_ids: list[str]) -> str:
    import json

    from app.models.chat_session import ChatMessage

    msg_id = str(uuid.uuid4())
    async with sm() as s:
        s.add(
            ChatMessage(
                id=msg_id,
                session_id="s1",
                role="assistant",
                content="answer",
                metadata_json=json.dumps({"exposed_learning_ids": exposed_ids}),
            )
        )
        await s.commit()
    return msg_id


async def _assert_credited_flag(session, message_id: str) -> None:
    import json

    from app.models.chat_session import ChatMessage

    row = await session.get(ChatMessage, message_id)
    meta = json.loads(row.metadata_json)
    assert meta.get("learning_credited_at_validation") is True


def _patch_factory(monkeypatch, sm) -> None:
    monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)


async def _times_applied(sm, lrn_id: str) -> int:
    async with sm() as s:
        row = await s.get(AgentLearning, lrn_id)
        return row.times_applied


class TestCreditValidatedLearnings:
    @pytest.mark.asyncio
    async def test_credits_on_clean_result(self, engine_and_sm, monkeypatch):
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", True, raising=False)
        lrn_id = await _seed(sm, "c1", times_applied=0)

        result = SimpleNamespace(error=None, exposed_learning_ids=[lrn_id])
        await chat_module.credit_validated_learnings(result, "c1")

        assert await _times_applied(sm, lrn_id) == 1

    @pytest.mark.asyncio
    async def test_skips_on_error_result(self, engine_and_sm, monkeypatch):
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", True, raising=False)
        lrn_id = await _seed(sm, "c1", times_applied=0)

        result = SimpleNamespace(error="boom", exposed_learning_ids=[lrn_id])
        await chat_module.credit_validated_learnings(result, "c1")

        assert await _times_applied(sm, lrn_id) == 0

    @pytest.mark.asyncio
    async def test_disabled_flag_suppresses_credit(self, engine_and_sm, monkeypatch):
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", False, raising=False)
        lrn_id = await _seed(sm, "c1", times_applied=0)

        result = SimpleNamespace(error=None, exposed_learning_ids=[lrn_id])
        await chat_module.credit_validated_learnings(result, "c1")

        assert await _times_applied(sm, lrn_id) == 0

    @pytest.mark.asyncio
    async def test_no_exposed_ids_is_noop(self, engine_and_sm, monkeypatch):
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", True, raising=False)
        result = SimpleNamespace(error=None, exposed_learning_ids=[])
        await chat_module.credit_validated_learnings(result, "c1")  # no raise

    @pytest.mark.asyncio
    async def test_skips_on_suspicious_result(self, engine_and_sm, monkeypatch):
        """Re-audit fix: a result the gate flagged suspicious must NOT be
        credited — that would reward learnings behind a likely-wrong answer."""
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", True, raising=False)
        lrn_id = await _seed(sm, "c1", times_applied=0)

        result = SimpleNamespace(error=None, suspicious_result=True, exposed_learning_ids=[lrn_id])
        await chat_module.credit_validated_learnings(result, "c1")

        assert await _times_applied(sm, lrn_id) == 0

    @pytest.mark.asyncio
    async def test_idempotent_per_message(self, engine_and_sm, monkeypatch):
        """Re-audit fix: crediting the same message twice (e.g. validation +
        a duplicate finalize, or validation followed by a thumbs-up) must bump
        times_applied only once."""
        _, sm = engine_and_sm
        _patch_factory(monkeypatch, sm)
        monkeypatch.setattr(settings, "learning_apply_on_validation_enabled", True, raising=False)
        lrn_id = await _seed(sm, "c1", times_applied=0)
        message_id = await _seed_message(sm, exposed_ids=[lrn_id])

        result = SimpleNamespace(error=None, exposed_learning_ids=[lrn_id])
        await chat_module.credit_validated_learnings(result, "c1", message_id=message_id)
        await chat_module.credit_validated_learnings(result, "c1", message_id=message_id)

        # Credited exactly once despite two calls for the same message.
        assert await _times_applied(sm, lrn_id) == 1
        # And the idempotency flag was persisted.
        async with sm() as s:
            await _assert_credited_flag(s, message_id)


class TestMaybeAutoInvestigate:
    """R5-7: a suspicious result must auto-route to the investigation agent when
    the feature is enabled and all routing identifiers are present, and must be
    a no-op otherwise."""

    def _suspicious_result(self):
        return SimpleNamespace(
            error=None,
            suspicious_result=True,
            suspicious_reason="validation failed",
            query="SELECT 1",
            results=SimpleNamespace(row_count=0, error=None),
        )

    def _trap_service(self, monkeypatch):
        """Install an InvestigationService whose use raises, so a no-op path is
        proven by the *absence* of an exception."""

        class _Trap:
            def __getattr__(self, _name):
                raise AssertionError("InvestigationService must not be used")

        monkeypatch.setattr(
            "app.services.investigation_service.InvestigationService",
            lambda: _Trap(),
            raising=False,
        )

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", False, raising=False)
        self._trap_service(monkeypatch)
        await chat_module.maybe_auto_investigate(
            self._suspicious_result(),
            project_id="p1",
            connection_id="c1",
            session_id="s1",
            message_id="m1",
        )

    @pytest.mark.asyncio
    async def test_not_suspicious_is_noop(self, monkeypatch):
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        self._trap_service(monkeypatch)
        clean = SimpleNamespace(error=None, suspicious_result=False)
        await chat_module.maybe_auto_investigate(
            clean,
            project_id="p1",
            connection_id="c1",
            session_id="s1",
            message_id="m1",
        )

    @pytest.mark.asyncio
    async def test_missing_message_id_is_noop(self, monkeypatch):
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        self._trap_service(monkeypatch)
        await chat_module.maybe_auto_investigate(
            self._suspicious_result(),
            project_id="p1",
            connection_id="c1",
            session_id="s1",
            message_id=None,
        )

    @pytest.mark.asyncio
    async def test_routes_when_enabled(self, engine_and_sm, monkeypatch):
        import asyncio

        _, sm = engine_and_sm
        monkeypatch.setattr(settings, "orchestrator_auto_investigate_enabled", True, raising=False)
        # B8: this test exercises the routing happy path, not budget enforcement
        # (covered in test_investigation_budget_and_verdict). With enforcement on,
        # an unseeded/unresolved owner would now (correctly) skip; disable it here
        # so routing proceeds regardless of owner resolution.
        monkeypatch.setattr(
            settings, "auto_investigate_budget_enforcement_enabled", False, raising=False
        )
        monkeypatch.setattr("app.models.base.async_session_factory", sm, raising=False)

        created: dict[str, object] = {}

        class _FakeSvc:
            async def create_investigation(self, _session, **kwargs):
                created.update(kwargs)
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

        await chat_module.maybe_auto_investigate(
            self._suspicious_result(),
            project_id="p1",
            connection_id="c1",
            session_id="s1",
            message_id="m1",
        )

        # An investigation was created with the auto complaint type, and the
        # background runner was scheduled.
        assert created.get("user_complaint_type") == "auto_suspicious"
        assert created.get("trigger_message_id") == "m1"
        assert tasks, "background investigation task must be scheduled"
        await asyncio.gather(*tasks)
        assert launched.get("investigation_id") == "inv-1"
        assert launched.get("connection_id") == "c1"
