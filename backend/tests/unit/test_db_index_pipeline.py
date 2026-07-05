"""Unit tests for DbIndexPipeline helpers and sample query generation."""

import asyncio
import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import ColumnInfo, QueryResult, SchemaInfo, TableInfo
from app.knowledge.db_index_pipeline import (
    DbIndexPipeline,
    _build_distinct_query,
    _detect_latest_record,
    _find_ordering_column,
    _is_enum_candidate,
    _sample_query,
    _sample_to_json,
)
from app.knowledge.db_index_validator import TableAnalysis


class TestFindOrderingColumn:
    def test_prefers_created_at(self):
        table = TableInfo(
            name="users",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="timestamp"),
                ColumnInfo(name="updated_at", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "created_at"

    def test_falls_back_to_pk(self):
        table = TableInfo(
            name="tags",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="name", data_type="varchar"),
            ],
        )
        assert _find_ordering_column(table) == "id"

    def test_case_insensitive(self):
        table = TableInfo(
            name="events",
            columns=[
                ColumnInfo(name="ID", data_type="int", is_primary_key=True),
                ColumnInfo(name="CreatedAt", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "CreatedAt"

    def test_no_suitable_column(self):
        table = TableInfo(
            name="pivot",
            columns=[
                ColumnInfo(name="left_id", data_type="int"),
                ColumnInfo(name="right_id", data_type="int"),
            ],
        )
        assert _find_ordering_column(table) is None

    def test_timestamp_column(self):
        table = TableInfo(
            name="logs",
            columns=[
                ColumnInfo(name="msg", data_type="text"),
                ColumnInfo(name="timestamp", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "timestamp"


class TestSampleQuery:
    def test_postgres_with_ordering(self):
        table = TableInfo(
            name="users",
            schema="public",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="timestamp"),
            ],
        )
        query, col = _sample_query(table, "postgres")
        assert '"users"' in query
        assert "ORDER BY" in query
        assert '"created_at"' in query
        assert "DESC LIMIT 3" in query
        assert col == "created_at"

    def test_mysql_with_ordering(self):
        table = TableInfo(
            name="orders",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="datetime"),
            ],
        )
        query, col = _sample_query(table, "mysql")
        assert "`orders`" in query
        assert "`created_at`" in query
        assert col == "created_at"

    def test_no_ordering_column(self):
        table = TableInfo(
            name="pivot",
            columns=[
                ColumnInfo(name="a_id", data_type="int"),
                ColumnInfo(name="b_id", data_type="int"),
            ],
        )
        query, col = _sample_query(table, "postgres")
        assert "ORDER BY" not in query
        assert "LIMIT 3" in query
        assert col is None

    def test_custom_limit(self):
        table = TableInfo(
            name="logs",
            columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
        )
        query, _ = _sample_query(table, "postgres", limit=5)
        assert "LIMIT 5" in query

    def test_non_public_schema(self):
        table = TableInfo(
            name="events",
            schema="analytics",
            columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
        )
        query, _ = _sample_query(table, "postgres")
        assert '"analytics"."events"' in query


class TestSampleToJson:
    def test_basic_conversion(self):
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"]],
            row_count=2,
        )
        data = json.loads(_sample_to_json(result))
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["name"] == "Bob"

    def test_empty_result(self):
        result = QueryResult(columns=[], rows=[], row_count=0)
        assert _sample_to_json(result) == "[]"

    def test_non_serializable_values(self):
        from datetime import datetime

        result = QueryResult(
            columns=["id", "created"],
            rows=[[1, datetime(2026, 3, 17)]],
            row_count=1,
        )
        data = json.loads(_sample_to_json(result))
        assert len(data) == 1
        assert "2026" in str(data[0]["created"])


class TestDetectLatestRecord:
    def test_with_timestamp(self):
        from datetime import datetime

        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, datetime(2026, 3, 17, 10, 30)]],
            row_count=1,
        )
        ts = _detect_latest_record(result, "created_at")
        assert ts is not None
        assert "2026-03-17" in ts

    def test_with_string_value(self):
        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, "2026-03-17 10:30:00"]],
            row_count=1,
        )
        ts = _detect_latest_record(result, "created_at")
        assert ts == "2026-03-17 10:30:00"

    def test_no_ordering_column(self):
        result = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        assert _detect_latest_record(result, None) is None

    def test_empty_rows(self):
        result = QueryResult(columns=["id"], rows=[], row_count=0)
        assert _detect_latest_record(result, "id") is None

    def test_none_value(self):
        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, None]],
            row_count=1,
        )
        assert _detect_latest_record(result, "created_at") is None

    def test_column_not_found(self):
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "test"]],
            row_count=1,
        )
        assert _detect_latest_record(result, "created_at") is None


class TestIsEnumCandidate:
    def test_status_column(self):
        assert _is_enum_candidate("status", "varchar", 1000) is True

    def test_type_column(self):
        assert _is_enum_candidate("user_type", "varchar", 500) is True

    def test_bool_type(self):
        assert _is_enum_candidate("is_active", "boolean", 100) is True

    def test_enum_type(self):
        assert _is_enum_candidate("role", "enum('admin','user')", 200) is True

    def test_flag_suffix(self):
        assert _is_enum_candidate("verified_flag", "int", 100) is True

    def test_regular_column(self):
        assert _is_enum_candidate("email", "varchar", 1000) is False

    def test_id_column(self):
        assert _is_enum_candidate("user_id", "int", 1000) is False

    def test_category_column(self):
        assert _is_enum_candidate("category", "varchar", 100) is True

    def test_payment_method(self):
        assert _is_enum_candidate("payment_method", "varchar", 100) is True


class TestIsEnumCandidateExtended:
    def test_country_column(self):
        assert _is_enum_candidate("country", "varchar", 1000) is True

    def test_name_column_excluded(self):
        assert _is_enum_candidate("name", "varchar", 1000) is False

    def test_currency_column(self):
        assert _is_enum_candidate("currency", "varchar", 500) is True

    def test_description_column_excluded(self):
        assert _is_enum_candidate("description", "text", 500) is False


class TestBuildDistinctQuerySqlite:
    def test_sqlite_no_quoting(self):
        table = TableInfo(
            name="events",
            columns=[ColumnInfo(name="type", data_type="text")],
        )
        q = _build_distinct_query(table, "type", "sqlite")
        assert "events" in q
        assert "type" in q
        assert "DISTINCT" in q
        assert "`" not in q
        assert '"' not in q


class TestBuildDistinctQuery:
    def test_postgres(self):
        table = TableInfo(
            name="orders",
            schema="public",
            columns=[ColumnInfo(name="status", data_type="varchar")],
        )
        q = _build_distinct_query(table, "status", "postgres")
        assert '"orders"' in q
        assert '"status"' in q
        assert "DISTINCT" in q
        assert "IS NOT NULL" in q

    def test_mysql(self):
        table = TableInfo(
            name="orders",
            columns=[ColumnInfo(name="status", data_type="varchar")],
        )
        q = _build_distinct_query(table, "status", "mysql")
        assert "`orders`" in q
        assert "`status`" in q

    def test_non_public_schema_postgres(self):
        table = TableInfo(
            name="events",
            schema="analytics",
            columns=[ColumnInfo(name="type", data_type="varchar")],
        )
        q = _build_distinct_query(table, "type", "postgres")
        assert '"analytics"."events"' in q


def _make_db_index_entry(table_name: str, schema: str = "public", **kw):
    """Lightweight stand-in for a DbIndex ORM row."""
    defaults = dict(
        table_name=table_name,
        table_schema=schema,
        is_active=True,
        relevance_score=4,
        business_description="reused desc",
        data_patterns="reused patterns",
        column_notes_json="{}",
        query_hints="reused hints",
        code_match_status="matched",
        code_match_details="reused details",
        numeric_format_notes="{}",
    )
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


class TestBuildReuseMap:
    """R2-3: incremental reuse of LLM analysis for unchanged tables."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _pipeline_with_stub(self, monkeypatch, *, prev_fp, entries, enabled=True):
        pipeline = DbIndexPipeline()
        summary = types.SimpleNamespace(schema_fingerprint=json.dumps(prev_fp))

        async def _get_summary(session, connection_id):
            return summary

        async def _get_index(session, connection_id):
            return entries

        monkeypatch.setattr(pipeline._svc, "get_summary", _get_summary)
        monkeypatch.setattr(pipeline._svc, "get_index", _get_index)

        import app.config as cfg

        monkeypatch.setattr(cfg.settings, "db_index_incremental_enabled", enabled)
        return pipeline

    def _schema(self):
        return SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    schema="public",
                    columns=[ColumnInfo(name="id", data_type="int")],
                ),
                TableInfo(
                    name="orders",
                    schema="public",
                    columns=[ColumnInfo(name="id", data_type="int")],
                ),
            ]
        )

    def test_reuses_unchanged_tables(self, monkeypatch):
        schema = self._schema()
        new_fp = schema.fingerprint()
        entries = [_make_db_index_entry("users"), _make_db_index_entry("orders")]
        pipeline = self._pipeline_with_stub(monkeypatch, prev_fp=new_fp, entries=entries)

        reuse = self._run(pipeline._build_reuse_map("conn1", new_fp))

        assert set(reuse) == {"users", "orders"}
        assert reuse["users"].business_description == "reused desc"

    def test_changed_table_not_reused(self, monkeypatch):
        schema = self._schema()
        new_fp = schema.fingerprint()
        prev_fp = dict(new_fp)
        # mutate the signature for orders -> should not be reused
        order_key = next(k for k in prev_fp if k.endswith("orders"))
        prev_fp[order_key] = "deadbeef0000"
        entries = [_make_db_index_entry("users"), _make_db_index_entry("orders")]
        pipeline = self._pipeline_with_stub(monkeypatch, prev_fp=prev_fp, entries=entries)

        reuse = self._run(pipeline._build_reuse_map("conn1", new_fp))

        assert "users" in reuse
        assert "orders" not in reuse

    def test_disabled_returns_empty(self, monkeypatch):
        schema = self._schema()
        new_fp = schema.fingerprint()
        entries = [_make_db_index_entry("users")]
        pipeline = self._pipeline_with_stub(
            monkeypatch, prev_fp=new_fp, entries=entries, enabled=False
        )

        reuse = self._run(pipeline._build_reuse_map("conn1", new_fp))

        assert reuse == {}

    def test_no_prior_fingerprint_returns_empty(self, monkeypatch):
        schema = self._schema()
        new_fp = schema.fingerprint()
        entries = [_make_db_index_entry("users")]
        pipeline = self._pipeline_with_stub(monkeypatch, prev_fp={}, entries=entries)

        reuse = self._run(pipeline._build_reuse_map("conn1", new_fp))

        assert reuse == {}


class TestRecomputeReusedIsActive:
    """R2-3 follow-up: a reused table's is_active is recomputed from fresh
    samples (data presence), while its LLM analysis is preserved."""

    @staticmethod
    def _reused(is_active: bool, relevance: int = 4) -> TableAnalysis:
        return TableAnalysis(
            table_name="t",
            is_active=is_active,
            relevance_score=relevance,
            business_description="reused desc",
        )

    def test_active_table_now_empty_becomes_inactive(self):
        reused = self._reused(is_active=True)
        out = DbIndexPipeline._recompute_reused_is_active(
            reused,
            fresh_sample=QueryResult(rows=[], row_count=0),
            row_count=0,
            sampling_failed=False,
        )
        assert out.is_active is False
        # LLM analysis (relevance/description) is preserved.
        assert out.relevance_score == 4
        assert out.business_description == "reused desc"

    def test_empty_table_now_has_rows_becomes_active(self):
        reused = self._reused(is_active=False)
        out = DbIndexPipeline._recompute_reused_is_active(
            reused,
            fresh_sample=QueryResult(rows=[[1]], row_count=1),
            row_count=0,
            sampling_failed=False,
        )
        assert out.is_active is True

    def test_active_by_row_count_even_without_sample_rows(self):
        reused = self._reused(is_active=False)
        out = DbIndexPipeline._recompute_reused_is_active(
            reused,
            fresh_sample=QueryResult(rows=[], row_count=0),
            row_count=500,
            sampling_failed=False,
        )
        assert out.is_active is True

    def test_failed_sampling_keeps_prior_is_active(self):
        """A failed sample falsely looks empty — keep the prior value rather
        than wrongly marking a live table inactive."""
        reused = self._reused(is_active=True)
        out = DbIndexPipeline._recompute_reused_is_active(
            reused,
            fresh_sample=QueryResult(rows=[], row_count=0),
            row_count=0,
            sampling_failed=True,
        )
        assert out.is_active is True
        # Unchanged object returned when nothing is recomputed.
        assert out is reused

    def test_unchanged_value_returns_same_object(self):
        reused = self._reused(is_active=True)
        out = DbIndexPipeline._recompute_reused_is_active(
            reused,
            fresh_sample=QueryResult(rows=[[1]], row_count=1),
            row_count=1,
            sampling_failed=False,
        )
        assert out is reused


# ---------------------------------------------------------------------------
# T8 — Pipeline routes sample/distinct through connector methods (Mongo-safe)
# DBIDX-D1/D2: the pipeline must call connector.sample_data() and
# connector.distinct_values() instead of building SQL strings and passing them
# to connector.execute_query(), which breaks for MongoDB (json.loads of SQL).
# ---------------------------------------------------------------------------


class _FakeConnector:
    """Minimal fake connector that records calls to sample_data/distinct_values."""

    db_type = "mongodb"

    def __init__(self) -> None:
        self.sampled: list[tuple[str, int]] = []
        self.distincted: list[tuple[str, str]] = []

    async def connect(self, cfg) -> None:  # noqa: ANN001
        pass

    async def disconnect(self) -> None:
        pass

    async def introspect_schema(self) -> SchemaInfo:
        return SchemaInfo(
            db_type="mongodb",
            tables=[
                TableInfo(
                    name="orders",
                    columns=[
                        ColumnInfo(name="status", data_type="str"),
                        ColumnInfo(name="_id", data_type="ObjectId", is_primary_key=True),
                    ],
                    row_count=10,
                )
            ],
        )

    async def sample_data(self, table_name: str, limit: int = 3) -> QueryResult:
        self.sampled.append((table_name, limit))
        return QueryResult(
            columns=["status", "_id"],
            rows=[["paid", "x1"], ["new", "x2"]],
            row_count=2,
        )

    async def distinct_values(self, table: str, column: str, limit: int = 50) -> list[str]:
        self.distincted.append((table, column))
        # NON-empty — the D2 regression was empty because SQL was sent to Mongo
        return ["paid", "new", "refunded"]

    async def approx_stats(self, table: str, column: str):  # noqa: ANN201
        from app.connectors.base import ColumnStats

        return ColumnStats(distinct_count=3, null_rate=0.0)


def _make_pipeline_mocks(monkeypatch: pytest.MonkeyPatch, fake_connector: _FakeConnector):
    """Wire a fake connector + stub LLM/service calls into the pipeline."""
    # Patch get_connector to return our fake
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.get_connector",
        lambda *a, **k: fake_connector,
    )

    # Stub tracker so pipeline steps don't need a real event loop / DB
    tracker = MagicMock()
    tracker.begin = AsyncMock(return_value="wf-test")
    tracker.end = AsyncMock()
    tracker.emit = AsyncMock()

    class _FakeStep:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    tracker.step = MagicMock(return_value=_FakeStep())

    # Stub DbIndexValidator to avoid LLM calls
    from app.knowledge.db_index_validator import TableAnalysis

    fake_analysis = TableAnalysis(
        table_name="orders",
        is_active=True,
        relevance_score=4,
        business_description="test",
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexValidator.analyze_table",
        AsyncMock(return_value=fake_analysis),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexValidator.analyze_table_batch",
        AsyncMock(return_value=[fake_analysis]),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexValidator.generate_summary",
        AsyncMock(return_value=MagicMock(summary_text="sum", recommendations="rec")),
    )

    # Capture upserted table_data dicts
    captured: list[dict] = []
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.upsert_table",
        AsyncMock(side_effect=lambda s, cid, td: captured.append(td) or MagicMock()),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.upsert_summary",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.delete_stale_tables",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.touch_heartbeat",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.get_summary",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.DbIndexService.get_index",
        AsyncMock(return_value=[]),
    )

    # Stub async_session_factory to avoid a real DB
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session():
        session = MagicMock()
        session.commit = AsyncMock()
        yield session

    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.async_session_factory",
        _fake_session,
    )

    # Stub heartbeat context manager
    import contextlib as _cm

    @_cm.asynccontextmanager
    async def _fake_heartbeat(fn, *, interval_seconds=30):
        yield

    monkeypatch.setattr(
        "app.knowledge.db_index_pipeline.heartbeat",
        _fake_heartbeat,
    )

    # Disable incremental + schema-change alert so those code paths are skipped
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "db_index_incremental_enabled", False)
    monkeypatch.setattr(cfg.settings, "schema_change_alerts_enabled", False)
    monkeypatch.setattr(cfg.settings, "schema_retrieval_enabled", False)
    monkeypatch.setattr(cfg.settings, "heartbeat_interval_seconds", 30)
    # T9: disable stats by default in the shared harness so existing T8 tests
    # are not affected; individual T9 tests opt in explicitly.
    monkeypatch.setattr(cfg.settings, "db_index_stats_enabled", False)
    monkeypatch.setattr(cfg.settings, "db_index_stats_max_columns", 20)

    return tracker, captured


class TestPipelineUsesConnectorMethods:
    """T8 / DBIDX-D1+D2: pipeline sample+distinct must go through connector methods."""

    @pytest.mark.asyncio
    async def test_pipeline_calls_sample_data_not_execute_query(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """connector.sample_data() must be called (not execute_query with SQL)."""
        fake = _FakeConnector()
        tracker, _ = _make_pipeline_mocks(monkeypatch, fake)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", cfg, "proj1", wf_id="wf-test")

        assert fake.sampled == [("orders", 3)], (
            "Pipeline must call connector.sample_data('orders', 3), not execute_query(SQL)"
        )

    @pytest.mark.asyncio
    async def test_pipeline_calls_distinct_values_not_execute_query(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """connector.distinct_values() must be called for enum-candidate columns."""
        fake = _FakeConnector()
        tracker, _ = _make_pipeline_mocks(monkeypatch, fake)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", cfg, "proj1", wf_id="wf-test")

        # 'status' is an enum candidate (in CANDIDATE_ENUM_PATTERNS)
        assert ("orders", "status") in fake.distincted, (
            "Pipeline must call connector.distinct_values('orders', 'status'), "
            "not execute_query(SQL DISTINCT ...)"
        )

    @pytest.mark.asyncio
    async def test_pipeline_distinct_values_populate_for_mongo(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The DBIDX-D2 regression: distinct values must be non-empty for Mongo."""
        fake = _FakeConnector()
        tracker, captured = _make_pipeline_mocks(monkeypatch, fake)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", cfg, "proj1", wf_id="wf-test")

        assert captured, "No table_data was upserted — pipeline may have failed"
        td = next((t for t in captured if t["table_name"] == "orders"), None)
        assert td is not None, "No orders entry in captured upsert calls"

        distinct_json = td["column_distinct_values_json"]
        assert '"status"' in distinct_json, (
            f"'status' key missing from column_distinct_values_json: {distinct_json}"
        )
        assert "paid" in distinct_json, (
            f"Expected distinct values ('paid') missing from JSON: {distinct_json}"
        )

    # -----------------------------------------------------------------------
    # T9 / DBIDX-D9: pipeline must collect approx_stats and persist them
    # into column_stats_json keyed by column name.
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_pipeline_persists_column_stats(self, monkeypatch: pytest.MonkeyPatch):
        """approx_stats results must be persisted into column_stats_json.

        _FakeConnector.approx_stats returns ColumnStats(distinct_count=3,
        null_rate=0.0) for every column.  After the pipeline run the upserted
        table_data for 'orders' must contain a 'column_stats_json' key whose
        JSON value has an entry for 'status' with the expected fields.
        """
        import app.config as cfg

        fake = _FakeConnector()
        tracker, captured = _make_pipeline_mocks(monkeypatch, fake)

        # Enable stats collection so the pipeline actually calls approx_stats.
        monkeypatch.setattr(cfg.settings, "db_index_stats_enabled", True)
        monkeypatch.setattr(cfg.settings, "db_index_stats_max_columns", 20)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        conn_cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", conn_cfg, "proj1", wf_id="wf-test")

        assert captured, "No table_data was upserted — pipeline may have failed"
        td = next((t for t in captured if t["table_name"] == "orders"), None)
        assert td is not None, "No orders entry in captured upsert calls"

        assert "column_stats_json" in td, (
            "table_data must include 'column_stats_json' key for T9 / DBIDX-D9"
        )
        stats = json.loads(td["column_stats_json"])
        assert "status" in stats, (
            f"'status' key missing from column_stats_json: {stats}"
        )
        assert stats["status"]["distinct_count"] == 3
        assert stats["status"]["null_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_pipeline_stats_disabled_skips_approx_stats(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When db_index_stats_enabled=False, approx_stats must NOT be called
        and column_stats_json must be empty ({})."""
        import app.config as cfg

        call_count = 0
        original_approx = _FakeConnector.approx_stats

        async def _counting_approx(self, table: str, column: str):  # noqa: ANN001
            nonlocal call_count
            call_count += 1
            return await original_approx(self, table, column)

        monkeypatch.setattr(_FakeConnector, "approx_stats", _counting_approx)

        fake = _FakeConnector()
        tracker, captured = _make_pipeline_mocks(monkeypatch, fake)
        monkeypatch.setattr(cfg.settings, "db_index_stats_enabled", False)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        conn_cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", conn_cfg, "proj1", wf_id="wf-test")

        assert call_count == 0, (
            f"approx_stats was called {call_count} time(s) even though stats are disabled"
        )
        td = next((t for t in captured if t["table_name"] == "orders"), None)
        if td and "column_stats_json" in td:
            assert json.loads(td["column_stats_json"]) == {}, (
                "column_stats_json must be empty when stats disabled"
            )

    @pytest.mark.asyncio
    async def test_pipeline_stats_cap_limits_columns(self, monkeypatch: pytest.MonkeyPatch):
        """db_index_stats_max_columns=1 must cap approx_stats calls to 1 per table."""
        import app.config as cfg

        fake = _FakeConnector()
        tracker, captured = _make_pipeline_mocks(monkeypatch, fake)
        monkeypatch.setattr(cfg.settings, "db_index_stats_enabled", True)
        monkeypatch.setattr(cfg.settings, "db_index_stats_max_columns", 1)

        stats_calls: list[tuple[str, str]] = []
        original_approx = _FakeConnector.approx_stats

        async def _recording_approx(self, table: str, column: str):  # noqa: ANN001
            stats_calls.append((table, column))
            return await original_approx(self, table, column)

        monkeypatch.setattr(_FakeConnector, "approx_stats", _recording_approx)

        from app.connectors.base import ConnectionConfig

        pipeline = DbIndexPipeline(workflow_tracker=tracker)
        conn_cfg = ConnectionConfig(db_type="mongodb", db_host="localhost", db_name="test")
        await pipeline.run("conn1", conn_cfg, "proj1", wf_id="wf-test")

        orders_calls = [c for c in stats_calls if c[0] == "orders"]
        assert len(orders_calls) <= 1, (
            f"Expected at most 1 approx_stats call for 'orders' with cap=1, "
            f"got {len(orders_calls)}: {orders_calls}"
        )
