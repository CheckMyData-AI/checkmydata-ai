"""R3 / F-LEARN-07 — cross-connection & global learning promotion stays within a tenant.

When ``cross_connection_learnings_enabled`` is on, ``get_global_patterns`` /
``promote_global_patterns`` must only aggregate learnings from connections that
belong to projects owned by the *same* user as the caller's connection. A
high-confidence pattern learned on tenant B's connection must never be promoted
into tenant A's prompt.
"""

import pytest

from app.models.agent_learning import AgentLearning, _lesson_hash
from app.services.agent_learning_service import AgentLearningService
from tests.integration.conftest import make_connection, make_project, make_user

pytestmark = pytest.mark.asyncio


async def _seed_global_pattern(
    db_session,
    connection_ids: list[str],
    *,
    lesson: str,
    category: str = "schema_gotcha",
    subject: str = "amounts",
    confidence: float = 0.9,
    times_confirmed: int = 3,
) -> str:
    """Seed the same lesson on every connection so it qualifies as a global pattern."""
    lesson_hash = _lesson_hash(lesson)
    for cid in connection_ids:
        db_session.add(
            AgentLearning(
                connection_id=cid,
                category=category,
                subject=subject,
                lesson=lesson,
                lesson_hash=lesson_hash,
                confidence=confidence,
                times_confirmed=times_confirmed,
                is_active=True,
            )
        )
    await db_session.commit()
    return lesson_hash


class TestGlobalPatternsTenantScoping:
    async def test_get_global_patterns_excludes_other_owner(self, db_session):
        """A pattern seen across tenant B's connections must not surface for tenant A."""
        owner_a = await make_user(db_session)
        owner_b = await make_user(db_session)

        proj_a = await make_project(db_session, owner_id=owner_a)
        proj_b = await make_project(db_session, owner_id=owner_b)

        a1 = await make_connection(db_session, project_id=proj_a)
        a2 = await make_connection(db_session, project_id=proj_a)
        b1 = await make_connection(db_session, project_id=proj_b)
        b2 = await make_connection(db_session, project_id=proj_b)

        # A's own cross-connection pattern (seen on a1 + a2).
        await _seed_global_pattern(db_session, [a1, a2], lesson="A: timestamps are stored in UTC")
        # B's cross-connection pattern (seen on b1 + b2) — must stay within B.
        await _seed_global_pattern(db_session, [b1, b2], lesson="B: amounts are stored in cents")

        svc = AgentLearningService()

        patterns_a = await svc.get_global_patterns(db_session, owner_user_id=owner_a)
        lessons_a = {p["lesson"] for p in patterns_a}
        assert "A: timestamps are stored in UTC" in lessons_a
        assert "B: amounts are stored in cents" not in lessons_a

        patterns_b = await svc.get_global_patterns(db_session, owner_user_id=owner_b)
        lessons_b = {p["lesson"] for p in patterns_b}
        assert "B: amounts are stored in cents" in lessons_b
        assert "A: timestamps are stored in UTC" not in lessons_b

    async def test_get_global_patterns_unresolved_owner_returns_empty(self, db_session):
        """Fail closed: an unknown owner scope yields no patterns."""
        owner = await make_user(db_session)
        proj = await make_project(db_session, owner_id=owner)
        c1 = await make_connection(db_session, project_id=proj)
        c2 = await make_connection(db_session, project_id=proj)
        await _seed_global_pattern(db_session, [c1, c2], lesson="some pattern")

        svc = AgentLearningService()
        patterns = await svc.get_global_patterns(
            db_session, owner_user_id="00000000-0000-0000-0000-000000000000"
        )
        assert patterns == []

    async def test_promote_global_patterns_excludes_other_tenant(self, db_session):
        """End-to-end: promoting for a connection in tenant A must not leak B's pattern."""
        owner_a = await make_user(db_session)
        owner_b = await make_user(db_session)
        proj_a = await make_project(db_session, owner_id=owner_a)
        proj_b = await make_project(db_session, owner_id=owner_b)

        a1 = await make_connection(db_session, project_id=proj_a)
        a2 = await make_connection(db_session, project_id=proj_a)
        target = await make_connection(db_session, project_id=proj_a)
        b1 = await make_connection(db_session, project_id=proj_b)
        b2 = await make_connection(db_session, project_id=proj_b)

        await _seed_global_pattern(db_session, [a1, a2], lesson="A: prefer the v2 orders table")
        await _seed_global_pattern(db_session, [b1, b2], lesson="B: secret tenant-B pattern")

        svc = AgentLearningService()
        # Promote for a connection that itself has no learnings yet, owned by A.
        lines = await svc.promote_global_patterns(db_session, target)
        joined = "\n".join(lines)
        assert "A: prefer the v2 orders table" in joined
        assert "B: secret tenant-B pattern" not in joined

    async def test_promote_global_patterns_unknown_connection_fails_closed(self, db_session):
        """An unresolvable connection (no owner) promotes nothing."""
        svc = AgentLearningService()
        lines = await svc.promote_global_patterns(db_session, "does-not-exist")
        assert lines == []
