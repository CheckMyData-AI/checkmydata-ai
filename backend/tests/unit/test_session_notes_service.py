"""Unit tests for SessionNotesService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.agent_learning  # noqa: F401
import app.models.benchmark  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.code_db_sync  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.data_validation  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.session_note  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.services.session_notes_service import SessionNotesService

svc = SessionNotesService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name=f"conn-{uuid.uuid4().hex[:6]}",
        db_type="postgresql",
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="user",
        db_password_encrypted="fake",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


class TestCreateNote:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Amount column stores cents, not dollars.",
        )
        assert note.id is not None
        assert note.category == "data_observation"
        assert note.subject == "orders"
        assert note.confidence == 0.7
        assert note.is_verified is False
        assert note.is_active is True

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        with pytest.raises(ValueError, match="Invalid note category"):
            await svc.create_note(
                db,
                connection_id=conn.id,
                project_id=proj.id,
                category="invalid_cat",
                subject="x",
                note="y",
            )

    @pytest.mark.asyncio
    async def test_exact_duplicate_bumps_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active, 0 = inactive.",
        )
        conf1 = note1.confidence

        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active, 0 = inactive.",
        )
        assert note2.id == note1.id
        assert note2.confidence > conf1


class TestFuzzyDedup:
    @pytest.mark.asyncio
    async def test_similar_note_merged(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Amount is stored in cents.",
        )
        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="The amount is stored in cents!",
        )
        assert note2.id == note1.id

    @pytest.mark.asyncio
    async def test_very_different_note_not_merged(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Amount is stored in cents.",
        )
        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Use LEFT JOIN when querying payment methods.",
        )
        assert note2.id != note1.id


class TestGetNotesForContext:
    @pytest.mark.asyncio
    async def test_filters_by_connection_and_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="High conf note",
            confidence=0.9,
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Very low conf note that should be totally different",
            confidence=0.1,
        )

        notes = await svc.get_notes_for_context(db, conn.id, min_confidence=0.3)
        assert len(notes) == 1
        assert "High conf" in notes[0].note

    @pytest.mark.asyncio
    async def test_filters_by_table_names(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Order status 1 = completed",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="User is_active is boolean",
        )

        notes = await svc.get_notes_for_context(db, conn.id, table_names=["orders"])
        assert all("orders" in n.subject.lower() or "order" in n.note.lower() for n in notes)


class TestCompileNotesPrompt:
    @pytest.mark.asyncio
    async def test_empty_returns_empty(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        prompt = await svc.compile_notes_prompt(db, conn.id)
        assert prompt == ""

    @pytest.mark.asyncio
    async def test_compiles_prompt_with_notes(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Status 1 = completed",
            confidence=0.9,
        )
        prompt = await svc.compile_notes_prompt(db, conn.id)
        assert "AGENT NOTES" in prompt
        assert "Business Logic" in prompt
        assert "orders" in prompt


class TestVerifyAndDeactivate:
    @pytest.mark.asyncio
    async def test_verify_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="column_mapping",
            subject="t",
            note="Col x maps to y",
        )
        assert note.is_verified is False
        original_confidence = note.confidence

        verified = await svc.verify_note(db, note.id)
        assert verified is not None
        assert verified.is_verified is True
        assert verified.confidence > original_confidence

    @pytest.mark.asyncio
    async def test_verify_nonexistent(self, db):
        result = await svc.verify_note(db, "no-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_note(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="x",
            note="Some observation",
        )
        result = await svc.deactivate_note(db, note.id)
        assert result is not None
        assert result.is_active is False


class TestCreateNoteVerified:
    @pytest.mark.asyncio
    async def test_exact_duplicate_with_verified_sets_flag(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active.",
            is_verified=False,
        )
        assert note1.is_verified is False

        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="users",
            note="Status 1 = active.",
            is_verified=True,
        )
        assert note2.id == note1.id
        assert note2.is_verified is True

    @pytest.mark.asyncio
    async def test_similar_note_with_verified_sets_flag(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note1 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="Amount is stored in cents.",
            is_verified=False,
        )

        note2 = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="payments",
            note="The amount is stored in cents!",
            is_verified=True,
        )
        assert note2.id == note1.id
        assert note2.is_verified is True


class TestGetNotesForContextCategory:
    @pytest.mark.asyncio
    async def test_filters_by_category(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Order status 1 = completed",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Order amounts in cents not dollars",
        )

        notes = await svc.get_notes_for_context(db, conn.id, category="business_logic")
        assert len(notes) == 1
        assert notes[0].category == "business_logic"


class TestGetNoteById:
    @pytest.mark.asyncio
    async def test_found(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="t",
            note="Some note text for get_note_by_id test",
        )
        result = await svc.get_note_by_id(db, note.id)
        assert result is not None
        assert result.id == note.id

    @pytest.mark.asyncio
    async def test_not_found(self, db):
        result = await svc.get_note_by_id(db, str(uuid.uuid4()))
        assert result is None


class TestCountNotes:
    @pytest.mark.asyncio
    async def test_counts_active(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="a",
            note="Active note",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="b",
            note="Another entirely different note for counting",
        )

        count = await svc.count_notes(db, conn.id)
        assert count == 2


class TestDeactivateNonexistent:
    @pytest.mark.asyncio
    async def test_returns_none(self, db):
        result = await svc.deactivate_note(db, str(uuid.uuid4()))
        assert result is None


class TestDecayStaleNotes:
    @pytest.mark.asyncio
    async def test_decay_returns_rowcount(self):
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute = AsyncMock(return_value=mock_result)

        count = await svc.decay_stale_notes(session, days_threshold=60, decay_amount=0.1)
        assert count == 3
        # Two execute calls: decay update + deactivation update.
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_decay_zero_when_no_stale(self):
        from unittest.mock import AsyncMock, MagicMock

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute = AsyncMock(return_value=mock_result)

        count = await svc.decay_stale_notes(session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_decay_executes_on_sqlite(self, db):
        """B1 (e2e audit): ``func.greatest()`` does not exist on SQLite, so the
        periodic decay UPDATE failed every cycle on SQLite deploys. The decay
        expression must be dialect-portable (real in-memory SQLite here)."""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.models.session_note import SessionNote

        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Stale observation that should decay",
            confidence=0.35,
        )
        # Age the note beyond the decay threshold.
        await db.execute(
            update(SessionNote)
            .where(SessionNote.id == note.id)
            .values(updated_at=datetime.now(UTC) - timedelta(days=90))
        )
        await db.commit()

        count = await svc.decay_stale_notes(db, days_threshold=60, decay_amount=0.1)
        assert count == 1
        await db.refresh(note)
        assert note.confidence == pytest.approx(0.25)
        assert note.is_active is True  # 0.25 >= deactivate_below (0.2)

    @pytest.mark.asyncio
    async def test_decay_floor_and_deactivation_on_sqlite(self, db):
        """Confidence decays to the 0.1 floor (greatest-equivalent), never below,
        and a note that lands under deactivate_below is deactivated."""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.models.session_note import SessionNote

        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        note = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="orders",
            note="Borderline note heading for deactivation",
            confidence=0.15,
        )
        await db.execute(
            update(SessionNote)
            .where(SessionNote.id == note.id)
            .values(updated_at=datetime.now(UTC) - timedelta(days=90))
        )
        await db.commit()

        count = await svc.decay_stale_notes(db, days_threshold=60, decay_amount=0.1)
        assert count == 1
        await db.refresh(note)
        # greatest(0.1, 0.15 - 0.1) == 0.1 — clamped at the floor, not 0.05.
        assert note.confidence == pytest.approx(0.1)
        assert note.is_active is False
        assert note.deactivated_at is not None


class TestNoteMentionsTable:
    """R4-6: word-boundary table match, not naive substring."""

    def test_subject_match(self):
        from types import SimpleNamespace

        note = SimpleNamespace(subject="Orders", note="anything here")
        assert svc._note_mentions_table(note, {"orders"}) is True

    def test_word_boundary_match_in_note_body(self):
        from types import SimpleNamespace

        note = SimpleNamespace(subject="misc", note="Join orders to payments by id")
        assert svc._note_mentions_table(note, {"orders"}) is True

    def test_no_spurious_substring_match(self):
        from types import SimpleNamespace

        # "users" must NOT match inside "power_users" or "businessusers".
        note = SimpleNamespace(subject="misc", note="The power_users table is special")
        assert svc._note_mentions_table(note, {"users"}) is False

    def test_underscore_table_name_not_partial(self):
        from types import SimpleNamespace

        note = SimpleNamespace(subject="misc", note="see my_order_items for details")
        assert svc._note_mentions_table(note, {"order_items"}) is False
        note2 = SimpleNamespace(subject="misc", note="see order_items for details")
        assert svc._note_mentions_table(note2, {"order_items"}) is True


class TestContradictionHandling:
    """R4-5/R4-6: conflict reconciliation aligned with the learning side —
    strict tie rule, same-polarity detection, exactly one active side."""

    @pytest.mark.asyncio
    async def test_strictly_stronger_contradiction_retires_incumbent(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        incumbent = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must always filter by deleted_at column.",
            confidence=0.7,
        )
        assert incumbent.is_active is True

        outranked = await svc._reconcile_contradictions(
            db,
            conn.id,
            "business_logic",
            "orders",
            "Rows must never filter by deleted_at column.",
            new_confidence=0.8,  # strictly higher than 0.7
            new_is_verified=False,
        )
        await db.refresh(incumbent)
        assert outranked is False
        assert incumbent.is_active is False
        assert incumbent.deactivated_at is not None

    @pytest.mark.asyncio
    async def test_confidence_tie_keeps_incumbent_and_outranks_new(self, db):
        """R4-5: a tie no longer lets the newcomer win — the incumbent stays
        and the new note is reported outranked (stored inactive by create_note)."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        incumbent = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must always filter by deleted_at column.",
            confidence=0.7,
        )
        outranked = await svc._reconcile_contradictions(
            db,
            conn.id,
            "business_logic",
            "orders",
            "Rows must never filter by deleted_at column.",
            new_confidence=0.7,  # tie
            new_is_verified=False,
        )
        await db.refresh(incumbent)
        assert outranked is True
        assert incumbent.is_active is True
        assert incumbent.deactivated_at is None

    @pytest.mark.asyncio
    async def test_verified_incumbent_survives_and_outranks_unverified_new(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        incumbent = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must always filter by deleted_at column.",
            confidence=0.5,
            is_verified=True,
        )
        # Even with higher confidence, an unverified note can't beat a verified
        # incumbent — verification dominates the ordering.
        outranked = await svc._reconcile_contradictions(
            db,
            conn.id,
            "business_logic",
            "orders",
            "Rows must never filter by deleted_at column.",
            new_confidence=0.9,
            new_is_verified=False,
        )
        await db.refresh(incumbent)
        assert outranked is True
        assert incumbent.is_active is True
        # No confidence penalty under the aligned rules.
        assert incumbent.confidence == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_same_polarity_divergence_is_a_conflict(self, db):
        """R4-5: 'use X' vs 'use Y' (same polarity) now reconciles, where the
        old opposite-polarity-only check missed it."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        incumbent = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Always join orders on the customer_id column.",
            confidence=0.6,
        )
        outranked = await svc._reconcile_contradictions(
            db,
            conn.id,
            "business_logic",
            "orders",
            "Always join orders on the account_id column.",
            new_confidence=0.9,
            new_is_verified=False,
        )
        await db.refresh(incumbent)
        # The stronger same-polarity divergent note supersedes the incumbent.
        assert outranked is False
        assert incumbent.is_active is False

    @pytest.mark.asyncio
    async def test_create_note_stores_outranked_note_inactive(self, db):
        """End-to-end: a weaker conflicting new note is created inactive so two
        contradictory notes never both feed the prompt."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must always filter by deleted_at column.",
            confidence=0.9,
            is_verified=True,
        )
        newcomer = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must never filter by deleted_at column.",
            confidence=0.5,
        )
        assert newcomer.is_active is False
        assert newcomer.deactivated_at is not None

    @pytest.mark.asyncio
    async def test_non_contradicting_note_untouched(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        incumbent = await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="orders",
            note="Rows must always filter by deleted_at column.",
            confidence=0.7,
        )
        outranked = await svc._reconcile_contradictions(
            db,
            conn.id,
            "business_logic",
            "orders",
            "Order totals are stored in cents.",
            new_confidence=0.9,
            new_is_verified=True,
        )
        await db.refresh(incumbent)
        assert outranked is False
        assert incumbent.is_active is True
        assert incumbent.confidence == pytest.approx(0.7)


class TestDeleteAllForConnection:
    @pytest.mark.asyncio
    async def test_delete_all(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="data_observation",
            subject="a",
            note="Note 1",
        )
        await svc.create_note(
            db,
            connection_id=conn.id,
            project_id=proj.id,
            category="business_logic",
            subject="b",
            note="Note 2 is entirely different from note 1",
        )

        count = await svc.delete_all_for_connection(db, conn.id)
        assert count == 2

        remaining = await svc.get_notes_for_context(db, conn.id, min_confidence=0.0)
        assert len(remaining) == 0
