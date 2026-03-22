"""Unit tests for CheckpointService."""

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.batch_query  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.scheduled_query  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.token_usage  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.indexing_checkpoint import IndexingCheckpoint
from app.models.project import Project
from app.services.checkpoint_service import (
    CheckpointService,
    _safe_json_loads_list,
    _safe_json_loads_set,
)

svc = CheckpointService()


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


class TestSafeJsonLoads:
    def test_loads_list_valid(self):
        assert _safe_json_loads_list('["a", "b"]') == ["a", "b"]

    def test_loads_list_invalid_json(self):
        assert _safe_json_loads_list("not json") == []

    def test_loads_list_not_a_list(self):
        assert _safe_json_loads_list('{"key": "val"}') == []

    def test_loads_list_none(self):
        assert _safe_json_loads_list(None) == []

    def test_loads_set_valid(self):
        assert _safe_json_loads_set('["a", "b", "a"]') == {"a", "b"}

    def test_loads_set_invalid(self):
        assert _safe_json_loads_set("bad") == set()


class TestGetActive:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self, db):
        proj = await _make_project(db)
        result = await svc.get_active(db, proj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_existing_checkpoint(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        result = await svc.get_active(db, proj.id)
        assert result is not None
        assert result.id == cp.id
        assert result.project_id == proj.id


class TestCreate:
    @pytest.mark.asyncio
    async def test_creates_with_status_running(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        assert cp.id is not None
        assert cp.project_id == proj.id
        assert cp.workflow_id == "wf-1"
        assert cp.head_sha == "sha-abc"
        assert cp.status == "running"
        assert cp.last_sha is None

    @pytest.mark.asyncio
    async def test_creates_with_last_sha(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc", last_sha="sha-old")
        assert cp.last_sha == "sha-old"

    @pytest.mark.asyncio
    async def test_deletes_existing_checkpoint_first(self, db):
        proj = await _make_project(db)
        cp1 = await svc.create(db, proj.id, "wf-1", "sha-aaa")
        cp2 = await svc.create(db, proj.id, "wf-2", "sha-bbb")

        assert cp2.id != cp1.id
        assert cp2.workflow_id == "wf-2"
        old = await db.get(IndexingCheckpoint, cp1.id)
        assert old is None


class TestCompleteStep:
    @pytest.mark.asyncio
    async def test_adds_step_to_completed_steps(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(db, cp.id, "fetch")
        await db.refresh(cp)
        steps = json.loads(cp.completed_steps)
        assert "fetch" in steps

    @pytest.mark.asyncio
    async def test_does_not_duplicate_step(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(db, cp.id, "fetch")
        await svc.complete_step(db, cp.id, "fetch")
        await db.refresh(cp)
        steps = json.loads(cp.completed_steps)
        assert steps.count("fetch") == 1

    @pytest.mark.asyncio
    async def test_updates_head_sha(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(db, cp.id, "fetch", head_sha="sha-new")
        await db.refresh(cp)
        assert cp.head_sha == "sha-new"

    @pytest.mark.asyncio
    async def test_updates_changed_files(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(db, cp.id, "diff", changed_files=["a.py", "b.py"])
        await db.refresh(cp)
        assert json.loads(cp.changed_files_json) == ["a.py", "b.py"]

    @pytest.mark.asyncio
    async def test_updates_deleted_files(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(db, cp.id, "diff", deleted_files=["old.py"])
        await db.refresh(cp)
        assert json.loads(cp.deleted_files_json) == ["old.py"]

    @pytest.mark.asyncio
    async def test_updates_profile_and_knowledge(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.complete_step(
            db,
            cp.id,
            "profile",
            profile_json='{"tables": 5}',
            knowledge_json='{"entities": 3}',
        )
        await db.refresh(cp)
        assert json.loads(cp.profile_json) == {"tables": 5}
        assert json.loads(cp.knowledge_json) == {"entities": 3}

    @pytest.mark.asyncio
    async def test_missing_checkpoint_is_noop(self, db):
        await svc.complete_step(db, "nonexistent", "fetch")

    @pytest.mark.asyncio
    async def test_updates_last_sha(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.complete_step(db, cp.id, "fetch", last_sha="sha-prev")
        await db.refresh(cp)
        assert cp.last_sha == "sha-prev"

    @pytest.mark.asyncio
    async def test_updates_total_docs(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.complete_step(db, cp.id, "embed", total_docs=42)
        await db.refresh(cp)
        assert cp.total_docs == 42


class TestMarkDocProcessed:
    @pytest.mark.asyncio
    async def test_adds_path(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.mark_doc_processed(db, cp.id, "docs/a.md")
        await db.refresh(cp)
        paths = json.loads(cp.processed_doc_paths)
        assert "docs/a.md" in paths

    @pytest.mark.asyncio
    async def test_does_not_duplicate_path(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.mark_doc_processed(db, cp.id, "docs/a.md")
        await svc.mark_doc_processed(db, cp.id, "docs/a.md")
        await db.refresh(cp)
        paths = json.loads(cp.processed_doc_paths)
        assert paths.count("docs/a.md") == 1

    @pytest.mark.asyncio
    async def test_missing_checkpoint_is_noop(self, db):
        await svc.mark_doc_processed(db, "nonexistent-id", "a.md")


class TestMarkDocsBatchProcessed:
    @pytest.mark.asyncio
    async def test_adds_multiple_paths(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.mark_docs_batch_processed(db, cp.id, ["a.md", "b.md", "c.md"])
        await db.refresh(cp)
        paths = json.loads(cp.processed_doc_paths)
        assert set(paths) == {"a.md", "b.md", "c.md"}

    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        original = cp.processed_doc_paths

        await svc.mark_docs_batch_processed(db, cp.id, [])
        await db.refresh(cp)
        assert cp.processed_doc_paths == original

    @pytest.mark.asyncio
    async def test_deduplicates_with_existing(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.mark_doc_processed(db, cp.id, "a.md")
        await svc.mark_docs_batch_processed(db, cp.id, ["a.md", "b.md"])
        await db.refresh(cp)
        paths = json.loads(cp.processed_doc_paths)
        assert paths.count("a.md") == 1
        assert "b.md" in paths

    @pytest.mark.asyncio
    async def test_missing_checkpoint_is_noop(self, db):
        await svc.mark_docs_batch_processed(db, "nonexistent-id", ["a.md"])


class TestMarkFailed:
    @pytest.mark.asyncio
    async def test_sets_status_and_error(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.mark_failed(db, cp.id, "embed", "Connection timeout")
        await db.refresh(cp)
        assert cp.status == "failed"
        assert cp.failed_step == "embed"
        assert cp.error_detail == "Connection timeout"

    @pytest.mark.asyncio
    async def test_truncates_long_error(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        long_error = "x" * 5000
        await svc.mark_failed(db, cp.id, "embed", long_error)
        await db.refresh(cp)
        assert len(cp.error_detail) == 4000

    @pytest.mark.asyncio
    async def test_missing_checkpoint_is_noop(self, db):
        await svc.mark_failed(db, "nonexistent-id", "embed", "error")


class TestDelete:
    @pytest.mark.asyncio
    async def test_removes_checkpoint(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")

        await svc.delete(db, cp.id)
        assert await db.get(IndexingCheckpoint, cp.id) is None

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, db):
        await svc.delete(db, "nonexistent-id")


class TestStaticMethods:
    @pytest.mark.asyncio
    async def test_get_completed_steps(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.complete_step(db, cp.id, "fetch")
        await svc.complete_step(db, cp.id, "profile")
        await db.refresh(cp)

        steps = CheckpointService.get_completed_steps(cp)
        assert steps == {"fetch", "profile"}

    @pytest.mark.asyncio
    async def test_get_processed_doc_paths(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.mark_doc_processed(db, cp.id, "a.md")
        await svc.mark_doc_processed(db, cp.id, "b.md")
        await db.refresh(cp)

        paths = CheckpointService.get_processed_doc_paths(cp)
        assert paths == {"a.md", "b.md"}

    @pytest.mark.asyncio
    async def test_get_changed_files(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.complete_step(db, cp.id, "diff", changed_files=["x.py", "y.py"])
        await db.refresh(cp)

        files = CheckpointService.get_changed_files(cp)
        assert files == ["x.py", "y.py"]

    @pytest.mark.asyncio
    async def test_get_deleted_files(self, db):
        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        await svc.complete_step(db, cp.id, "diff", deleted_files=["old.py"])
        await db.refresh(cp)

        files = CheckpointService.get_deleted_files(cp)
        assert files == ["old.py"]

    def test_get_completed_steps_empty(self):
        cp = IndexingCheckpoint(project_id="p", workflow_id="w", head_sha="s", completed_steps="[]")
        assert CheckpointService.get_completed_steps(cp) == set()

    def test_get_changed_files_empty(self):
        cp = IndexingCheckpoint(
            project_id="p", workflow_id="w", head_sha="s", changed_files_json="[]"
        )
        assert CheckpointService.get_changed_files(cp) == []


class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_deletes_stale_checkpoints(self, db):
        from datetime import UTC, datetime, timedelta

        proj = await _make_project(db)
        cp = await svc.create(db, proj.id, "wf-1", "sha-abc")
        cp.updated_at = datetime.now(UTC) - timedelta(hours=48)
        await db.commit()

        count = await svc.cleanup_stale(db, max_age_hours=24)
        assert count == 1
        result = await svc.get_active(db, proj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_stale_checkpoints(self, db):
        proj = await _make_project(db)
        await svc.create(db, proj.id, "wf-1", "sha-abc")
        count = await svc.cleanup_stale(db, max_age_hours=24)
        assert count == 0
