"""Unit tests for CodeDbSyncService."""

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.batch_query  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.code_db_sync  # noqa: F401
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
from app.models.connection import Connection
from app.models.project import Project
from app.services.code_db_sync_service import CodeDbSyncService

svc = CodeDbSyncService()


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
        name="test-conn",
        db_type="postgresql",
        db_port=5432,
        db_name="testdb",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


class TestUpsertTableSync:
    @pytest.mark.asyncio
    async def test_creates_new_entry(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        entry = await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "users",
                "entity_name": "User",
                "sync_status": "matched",
                "confidence_score": 5,
            },
        )
        await db.commit()

        assert entry.id is not None
        assert entry.table_name == "users"
        assert entry.entity_name == "User"
        assert entry.sync_status == "matched"
        assert entry.confidence_score == 5

    @pytest.mark.asyncio
    async def test_updates_existing_entry(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "users",
                "sync_status": "unknown",
                "confidence_score": 2,
            },
        )
        await db.commit()

        updated = await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "users",
                "sync_status": "matched",
                "confidence_score": 5,
            },
        )
        await db.commit()

        assert updated.sync_status == "matched"
        assert updated.confidence_score == 5


class TestGetSync:
    @pytest.mark.asyncio
    async def test_returns_entries_ordered_by_confidence(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "low_conf",
                "confidence_score": 1,
            },
        )
        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "high_conf",
                "confidence_score": 5,
            },
        )
        await db.commit()

        entries = await svc.get_sync(db, conn.id)
        assert len(entries) == 2
        assert entries[0].table_name == "high_conf"
        assert entries[1].table_name == "low_conf"

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_connection(self, db):
        entries = await svc.get_sync(db, "nonexistent")
        assert entries == []


class TestGetTableSync:
    @pytest.mark.asyncio
    async def test_returns_specific_table(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(db, conn.id, {"table_name": "orders"})
        await db.commit()

        entry = await svc.get_table_sync(db, conn.id, "orders")
        assert entry is not None
        assert entry.table_name == "orders"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_table(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        entry = await svc.get_table_sync(db, conn.id, "nonexistent")
        assert entry is None


class TestDeleteStaleTables:
    @pytest.mark.asyncio
    async def test_removes_tables_not_in_current_set(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(db, conn.id, {"table_name": "keep"})
        await svc.upsert_table_sync(db, conn.id, {"table_name": "remove"})
        await db.commit()

        deleted = await svc.delete_stale_tables(db, conn.id, {"keep"})
        await db.commit()

        assert deleted == 1
        entries = await svc.get_sync(db, conn.id)
        assert len(entries) == 1
        assert entries[0].table_name == "keep"

    @pytest.mark.asyncio
    async def test_no_deletions_when_all_current(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(db, conn.id, {"table_name": "a"})
        await svc.upsert_table_sync(db, conn.id, {"table_name": "b"})
        await db.commit()

        deleted = await svc.delete_stale_tables(db, conn.id, {"a", "b"})
        assert deleted == 0


class TestDeleteAll:
    @pytest.mark.asyncio
    async def test_removes_all_entries_and_summary(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_table_sync(db, conn.id, {"table_name": "t1"})
        await svc.upsert_summary(db, conn.id, {"total_tables": 1})
        await db.commit()

        await svc.delete_all(db, conn.id)

        entries = await svc.get_sync(db, conn.id)
        assert entries == []
        summary = await svc.get_summary(db, conn.id)
        assert summary is None


class TestSummary:
    @pytest.mark.asyncio
    async def test_upsert_creates_summary(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        summary = await svc.upsert_summary(
            db,
            conn.id,
            {
                "total_tables": 10,
                "synced_tables": 8,
                "code_only_tables": 1,
                "db_only_tables": 1,
            },
        )
        await db.commit()

        assert summary.total_tables == 10
        assert summary.synced_tables == 8

    @pytest.mark.asyncio
    async def test_upsert_updates_summary(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.upsert_summary(db, conn.id, {"total_tables": 5})
        await db.commit()

        updated = await svc.upsert_summary(db, conn.id, {"total_tables": 10})
        await db.commit()

        assert updated.total_tables == 10

    @pytest.mark.asyncio
    async def test_get_summary_returns_none_when_missing(self, db):
        summary = await svc.get_summary(db, "nonexistent")
        assert summary is None


class TestStatusHelpers:
    @pytest.mark.asyncio
    async def test_is_synced_false_when_no_summary(self, db):
        result = await svc.is_synced(db, "no-conn")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_synced_true_when_completed(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.set_sync_status(db, conn.id, "completed")
        await db.commit()

        assert await svc.is_synced(db, conn.id) is True

    @pytest.mark.asyncio
    async def test_is_synced_false_when_running(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.set_sync_status(db, conn.id, "running")
        await db.commit()

        assert await svc.is_synced(db, conn.id) is False

    @pytest.mark.asyncio
    async def test_set_sync_status_creates_summary_if_missing(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.set_sync_status(db, conn.id, "running")
        await db.commit()

        summary = await svc.get_summary(db, conn.id)
        assert summary is not None
        assert summary.sync_status == "running"

    @pytest.mark.asyncio
    async def test_set_sync_status_updates_existing(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)

        await svc.set_sync_status(db, conn.id, "running")
        await db.commit()
        await svc.set_sync_status(db, conn.id, "completed")
        await db.commit()

        summary = await svc.get_summary(db, conn.id)
        assert summary.sync_status == "completed"

    @pytest.mark.asyncio
    async def test_get_sync_status_idle_when_no_summary(self, db):
        status = await svc.get_sync_status(db, "no-conn")
        assert status == "idle"

    @pytest.mark.asyncio
    async def test_get_sync_status_returns_actual(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.set_sync_status(db, conn.id, "failed")
        await db.commit()

        assert await svc.get_sync_status(db, conn.id) == "failed"

    @pytest.mark.asyncio
    async def test_get_status_dict_when_no_summary(self, db):
        result = await svc.get_status(db, "no-conn")
        assert result == {"is_synced": False}

    @pytest.mark.asyncio
    async def test_get_status_dict_when_completed(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_summary(
            db,
            conn.id,
            {
                "total_tables": 5,
                "synced_tables": 4,
                "code_only_tables": 1,
                "db_only_tables": 0,
                "mismatch_tables": 0,
                "sync_status": "completed",
            },
        )
        await db.commit()

        status = await svc.get_status(db, conn.id)
        assert status["is_synced"] is True
        assert status["total_tables"] == 5
        assert status["is_syncing"] is False


class TestMarkStale:
    @pytest.mark.asyncio
    async def test_marks_completed_as_stale(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.set_sync_status(db, conn.id, "completed")
        await db.commit()

        await svc.mark_stale(db, conn.id)
        await db.commit()

        assert await svc.get_sync_status(db, conn.id) == "stale"

    @pytest.mark.asyncio
    async def test_does_not_mark_running_as_stale(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.set_sync_status(db, conn.id, "running")
        await db.commit()

        await svc.mark_stale(db, conn.id)
        await db.commit()

        assert await svc.get_sync_status(db, conn.id) == "running"


class TestMarkStaleForProject:
    @pytest.mark.asyncio
    async def test_marks_all_project_connections_stale(self, db):
        proj = await _make_project(db)
        conn1 = await _make_connection(db, proj.id)
        conn2 = await _make_connection(db, proj.id)

        await svc.set_sync_status(db, conn1.id, "completed")
        await svc.set_sync_status(db, conn2.id, "completed")
        await db.commit()

        await svc.mark_stale_for_project(db, proj.id)
        await db.commit()

        assert await svc.get_sync_status(db, conn1.id) == "stale"
        assert await svc.get_sync_status(db, conn2.id) == "stale"

    @pytest.mark.asyncio
    async def test_no_op_for_project_without_connections(self, db):
        proj = await _make_project(db)
        await svc.mark_stale_for_project(db, proj.id)


class TestAddRuntimeEnrichment:
    @pytest.mark.asyncio
    async def test_merges_json_field(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "orders",
                "required_filters_json": json.dumps({"active": "is_deleted = 0"}),
            },
        )
        await db.commit()

        result = await svc.add_runtime_enrichment(
            db, conn.id, "orders", "required_filters_json", json.dumps({"paid": "status = 'paid'"})
        )
        await db.commit()

        assert result is not None
        data = json.loads(result.required_filters_json)
        assert "active" in data
        assert "paid" in data

    @pytest.mark.asyncio
    async def test_appends_text_field(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "orders",
                "query_recommendations": "Use index on created_at",
            },
        )
        await db.commit()

        result = await svc.add_runtime_enrichment(
            db, conn.id, "orders", "query_recommendations", "Filter by status first"
        )
        await db.commit()

        assert "Use index on created_at" in result.query_recommendations
        assert "Filter by status first" in result.query_recommendations

    @pytest.mark.asyncio
    async def test_rejects_unsupported_field(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(db, conn.id, {"table_name": "orders"})
        await db.commit()

        result = await svc.add_runtime_enrichment(db, conn.id, "orders", "entity_name", "NewName")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_table(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        result = await svc.add_runtime_enrichment(
            db, conn.id, "nonexistent", "query_recommendations", "tip"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_invalid_json_in_existing(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "orders",
                "required_filters_json": "not-json",
            },
        )
        await db.commit()

        result = await svc.add_runtime_enrichment(
            db, conn.id, "orders", "required_filters_json", json.dumps({"new": "value"})
        )
        await db.commit()

        data = json.loads(result.required_filters_json)
        assert data == {"new": "value"}

    @pytest.mark.asyncio
    async def test_does_not_duplicate_text(self, db):
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {
                "table_name": "orders",
                "query_recommendations": "existing tip",
            },
        )
        await db.commit()

        result = await svc.add_runtime_enrichment(
            db, conn.id, "orders", "query_recommendations", "existing tip"
        )
        await db.commit()

        assert result.query_recommendations.count("existing tip") == 1


def _stub_entry(**kwargs):
    """Create a CodeDbSync-like object without SQLAlchemy instrumentation."""

    class _Stub:
        pass

    defaults = {
        "table_name": "test",
        "sync_status": "matched",
        "confidence_score": 3,
        "conversion_warnings": "",
        "data_format_notes": "",
        "query_recommendations": "",
        "entity_name": None,
        "entity_file_path": None,
        "read_count": 0,
        "write_count": 0,
        "business_logic_notes": "",
        "column_sync_notes_json": "{}",
        "used_in_files_json": "[]",
        "synced_at": None,
    }
    defaults.update(kwargs)
    obj = _Stub()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _stub_summary(**kwargs):
    class _Stub:
        pass

    defaults = {
        "total_tables": 0,
        "synced_tables": 0,
        "code_only_tables": 0,
        "db_only_tables": 0,
        "mismatch_tables": 0,
        "global_notes": "",
        "data_conventions": "",
        "query_guidelines": "",
        "synced_at": None,
    }
    defaults.update(kwargs)
    obj = _Stub()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


class TestSyncToPromptContext:
    def test_empty_entries_returns_empty(self):
        assert CodeDbSyncService.sync_to_prompt_context([], None) == ""

    def test_includes_conversion_warnings(self):
        entry = _stub_entry(table_name="orders", conversion_warnings="amount in cents")
        result = CodeDbSyncService.sync_to_prompt_context([entry], None)
        assert "CRITICAL" in result
        assert "amount in cents" in result

    def test_includes_matched_tables(self):
        entry = _stub_entry(
            table_name="users",
            sync_status="matched",
            data_format_notes="timestamps UTC",
            query_recommendations="filter active",
        )
        result = CodeDbSyncService.sync_to_prompt_context([entry], None)
        assert "users" in result
        assert "timestamps UTC" in result

    def test_includes_code_only_db_only_counts(self):
        entries = [
            _stub_entry(table_name="a", sync_status="code_only"),
            _stub_entry(table_name="b", sync_status="db_only"),
        ]
        result = CodeDbSyncService.sync_to_prompt_context(entries, None)
        assert "1 code-only" in result
        assert "1 DB-only" in result


class TestTableSyncToDetail:
    def test_includes_all_fields(self):
        entry = _stub_entry(
            table_name="orders",
            sync_status="matched",
            confidence_score=4,
            entity_name="Order",
            entity_file_path="models/order.py",
            read_count=5,
            write_count=2,
            conversion_warnings="amount in cents",
            data_format_notes="timestamps in UTC",
            business_logic_notes="soft delete pattern",
            query_recommendations="always filter is_deleted",
            column_sync_notes_json=json.dumps({"amount": "stored in cents"}),
            used_in_files_json=json.dumps(["api/orders.py", "services/billing.py"]),
        )
        result = CodeDbSyncService.table_sync_to_detail(entry)
        assert "orders" in result
        assert "Order" in result
        assert "models/order.py" in result
        assert "amount in cents" in result
        assert "timestamps in UTC" in result
        assert "soft delete pattern" in result
        assert "always filter is_deleted" in result
        assert "stored in cents" in result
        assert "api/orders.py" in result

    def test_handles_empty_json_fields(self):
        entry = _stub_entry(
            table_name="orders",
            column_sync_notes_json="{}",
            used_in_files_json="[]",
            entity_name=None,
            entity_file_path=None,
            conversion_warnings="",
            data_format_notes="",
            business_logic_notes="",
            query_recommendations="",
        )
        result = CodeDbSyncService.table_sync_to_detail(entry)
        assert "Column notes" not in result
        assert "Used in" not in result


class TestSyncToResponse:
    def test_returns_tables_list(self):
        entries = [_stub_entry(table_name="a"), _stub_entry(table_name="b")]
        result = CodeDbSyncService.sync_to_response(entries, None)
        assert len(result["tables"]) == 2
        assert result["tables"][0]["table_name"] == "a"
        assert "summary" not in result

    def test_includes_summary_when_present(self):
        s = _stub_summary(
            total_tables=5,
            synced_tables=4,
            code_only_tables=1,
            global_notes="notes",
            data_conventions="conv",
            query_guidelines="guide",
        )
        result = CodeDbSyncService.sync_to_response([], s)
        assert result["summary"]["total_tables"] == 5
        assert result["summary"]["global_notes"] == "notes"


class TestSyncToPromptContextEdgeCases:
    def test_with_summary_datetime(self):
        """Cover line 323: summary with synced_at."""
        from datetime import UTC, datetime

        s = _stub_summary(
            synced_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            global_notes="Project uses UTC timestamps",
            data_conventions="All amounts in cents",
            query_guidelines="Always use LIMIT",
        )
        entries = [_stub_entry(table_name="orders", sync_status="matched")]
        result = CodeDbSyncService.sync_to_prompt_context(entries, s)
        assert "Code-DB Sync (analyzed 2026-03-01" in result
        assert "Project uses UTC timestamps" in result
        assert "All amounts in cents" in result
        assert "Always use LIMIT" in result

    def test_prompt_with_warnings(self):
        entries = [_stub_entry(table_name="orders", conversion_warnings="Amount stored in cents!")]
        result = CodeDbSyncService.sync_to_prompt_context(entries, None)
        assert "CRITICAL" in result
        assert "Amount stored in cents!" in result

    def test_prompt_with_code_only_tables(self):
        entries = [
            _stub_entry(table_name="a", sync_status="code_only"),
            _stub_entry(table_name="b", sync_status="db_only"),
        ]
        result = CodeDbSyncService.sync_to_prompt_context(entries, None)
        assert "code-only" in result
        assert "DB-only" in result


class TestTableSyncToDetailEdgeCases:
    def test_bad_column_sync_notes_json(self):
        """Cover lines 408-409: invalid column notes JSON."""
        entry = _stub_entry(
            table_name="orders",
            column_sync_notes_json="not valid json!!!",
        )
        result = CodeDbSyncService.table_sync_to_detail(entry)
        assert "orders" in result

    def test_bad_used_in_files_json(self):
        """Cover lines 416-417: invalid files JSON."""
        entry = _stub_entry(
            table_name="orders",
            used_in_files_json="not valid json!!!",
        )
        result = CodeDbSyncService.table_sync_to_detail(entry)
        assert "orders" in result
