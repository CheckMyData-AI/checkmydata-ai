"""Comprehensive unit tests for InsightFeedAgent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.insight_feed_agent import FeedScanResult, InsightFeedAgent

# ---------------------------------------------------------------------------
# FeedScanResult dataclass
# ---------------------------------------------------------------------------


class TestFeedScanResult:
    def test_defaults(self):
        result = FeedScanResult()
        assert result.insights_created == 0
        assert result.insights_updated == 0
        assert result.queries_run == 0
        assert result.errors == []

    def test_errors_default_factory_is_independent(self):
        r1 = FeedScanResult()
        r2 = FeedScanResult()
        r1.errors.append("boom")
        assert r2.errors == []

    def test_custom_values(self):
        result = FeedScanResult(
            insights_created=3,
            insights_updated=2,
            queries_run=5,
            errors=["e1"],
        )
        assert result.insights_created == 3
        assert result.insights_updated == 2
        assert result.queries_run == 5
        assert result.errors == ["e1"]


# ---------------------------------------------------------------------------
# _map_insight_type (static)
# ---------------------------------------------------------------------------


class TestMapInsightType:
    def test_trend_up(self):
        assert InsightFeedAgent._map_insight_type("trend_up") == "trend"

    def test_trend_down(self):
        assert InsightFeedAgent._map_insight_type("trend_down") == "trend"

    def test_trend_any_suffix(self):
        assert InsightFeedAgent._map_insight_type("trend_flat") == "trend"

    def test_outlier(self):
        assert InsightFeedAgent._map_insight_type("outlier") == "anomaly"

    def test_concentration(self):
        assert InsightFeedAgent._map_insight_type("concentration") == "pattern"

    def test_summary(self):
        assert InsightFeedAgent._map_insight_type("summary") == "observation"

    def test_unknown_falls_back_to_observation(self):
        assert InsightFeedAgent._map_insight_type("unknown") == "observation"

    def test_empty_string(self):
        assert InsightFeedAgent._map_insight_type("") == "observation"


# ---------------------------------------------------------------------------
# _map_severity (static)
# ---------------------------------------------------------------------------


class TestMapSeverity:
    def test_outlier_high_confidence(self):
        assert InsightFeedAgent._map_severity("outlier", 0.8) == "warning"

    def test_outlier_low_confidence(self):
        assert InsightFeedAgent._map_severity("outlier", 0.5) == "info"

    def test_outlier_boundary(self):
        assert InsightFeedAgent._map_severity("outlier", 0.7) == "info"

    def test_trend_up_high_confidence(self):
        assert InsightFeedAgent._map_severity("trend_up", 0.9) == "warning"

    def test_trend_up_medium_confidence(self):
        assert InsightFeedAgent._map_severity("trend_up", 0.5) == "info"

    def test_trend_down_at_boundary(self):
        assert InsightFeedAgent._map_severity("trend_down", 0.8) == "info"

    def test_trend_down_above_boundary(self):
        assert InsightFeedAgent._map_severity("trend_down", 0.81) == "warning"

    def test_concentration_high_confidence(self):
        assert InsightFeedAgent._map_severity("concentration", 0.8) == "info"

    def test_concentration_low_confidence(self):
        assert InsightFeedAgent._map_severity("concentration", 0.5) == "info"

    def test_other_type_max_confidence(self):
        assert InsightFeedAgent._map_severity("other", 1.0) == "info"

    def test_summary_type(self):
        assert InsightFeedAgent._map_severity("summary", 0.9) == "info"


# ---------------------------------------------------------------------------
# Helpers for building an agent with mocked internals
# ---------------------------------------------------------------------------


def _make_agent() -> InsightFeedAgent:
    """Create an InsightFeedAgent with all internal services mocked out."""
    with (
        patch("app.agents.insight_feed_agent.InsightMemoryService"),
        patch("app.agents.insight_feed_agent.TrustService"),
        patch("app.agents.insight_feed_agent.InsightGenerator"),
    ):
        agent = InsightFeedAgent()
    agent._memory = MagicMock()
    agent._memory.store_insight = AsyncMock()
    agent._trust = MagicMock()
    agent._insight_gen = MagicMock()
    return agent


def _make_db_entry(
    table_name: str = "orders",
    column_notes_json: str | None = None,
    sample_data_json: str | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.table_name = table_name
    entry.column_notes_json = column_notes_json
    entry.sample_data_json = sample_data_json
    return entry


# ---------------------------------------------------------------------------
# _analyze_table
# ---------------------------------------------------------------------------


class TestAnalyzeTable:
    @pytest.mark.asyncio
    async def test_empty_table_name_returns_empty(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="")
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []
        agent._insight_gen.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_table_name_attr_returns_empty(self):
        agent = _make_agent()
        entry = MagicMock(spec=[])  # no attributes
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_with_valid_sample_data(self):
        agent = _make_agent()
        col_notes = {"amount": "total order amount", "status": "order status"}
        sample_rows = [
            {"amount": 100, "status": "paid"},
            {"amount": 200, "status": "pending"},
        ]
        entry = _make_db_entry(
            table_name="orders",
            column_notes_json=json.dumps(col_notes),
            sample_data_json=json.dumps(sample_rows),
        )
        agent._insight_gen.analyze.return_value = [
            {
                "type": "trend_up",
                "title": "Rising amounts",
                "description": "Amounts are going up",
                "confidence": 0.75,
            },
        ]
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert len(result) == 1
        assert result[0]["title"] == "[orders] Rising amounts"
        assert result[0]["type"] == "trend"
        assert result[0]["confidence"] == 0.75
        assert result[0]["sample_size"] == 2
        agent._insight_gen.analyze.assert_called_once_with(
            sample_rows,
            ["amount", "status"],
        )

    @pytest.mark.asyncio
    async def test_insight_severity_mapped(self):
        agent = _make_agent()
        col_notes = {"col1": "note"}
        sample_rows = [{"col1": 1}]
        entry = _make_db_entry(
            table_name="t",
            column_notes_json=json.dumps(col_notes),
            sample_data_json=json.dumps(sample_rows),
        )
        agent._insight_gen.analyze.return_value = [
            {"type": "outlier", "title": "spike", "description": "d", "confidence": 0.9},
        ]
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result[0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_bad_column_notes_json(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="users",
            column_notes_json="NOT VALID JSON {{{",
            sample_data_json=json.dumps([{"a": 1}]),
        )
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []
        agent._insight_gen.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_bad_sample_data_json(self):
        agent = _make_agent()
        col_notes = {"col": "note"}
        entry = _make_db_entry(
            table_name="users",
            column_notes_json=json.dumps(col_notes),
            sample_data_json="[BROKEN",
        )
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []
        agent._insight_gen.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_column_notes(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="items",
            column_notes_json=None,
            sample_data_json=json.dumps([{"x": 1}]),
        )
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_none_sample_data(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="items",
            column_notes_json=json.dumps({"col": "n"}),
            sample_data_json=None,
        )
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_rows_skips_analyze(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="items",
            column_notes_json=json.dumps({"col": "n"}),
            sample_data_json=json.dumps([]),
        )
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result == []
        agent._insight_gen.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_connector_and_llm_triggers_deep_analysis(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="orders")
        entry.column_notes_json = None
        entry.sample_data_json = None
        session = AsyncMock()
        connector = MagicMock()
        llm = MagicMock()

        agent._llm_deep_analysis = AsyncMock(
            return_value=[
                {"type": "observation", "title": "[orders] LLM insight", "description": "d"},
            ]
        )

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
            connector=connector,
            llm=llm,
        )

        agent._llm_deep_analysis.assert_awaited_once()
        assert len(result) == 1
        assert result[0]["title"] == "[orders] LLM insight"

    @pytest.mark.asyncio
    async def test_no_connector_skips_deep_analysis(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="orders")
        entry.column_notes_json = None
        entry.sample_data_json = None
        session = AsyncMock()

        agent._llm_deep_analysis = AsyncMock()

        await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
            connector=None,
            llm=MagicMock(),
        )

        agent._llm_deep_analysis.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_columns_capped_at_20(self):
        agent = _make_agent()
        cols = {f"c{i}": f"note{i}" for i in range(30)}
        entry = _make_db_entry(
            table_name="wide",
            column_notes_json=json.dumps(cols),
            sample_data_json=json.dumps([{f"c{i}": i for i in range(30)}]),
        )
        agent._insight_gen.analyze.return_value = []
        session = AsyncMock()

        await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        call_args = agent._insight_gen.analyze.call_args
        passed_columns = call_args[0][1]
        assert len(passed_columns) == 20

    @pytest.mark.asyncio
    async def test_rows_capped_at_50(self):
        agent = _make_agent()
        many_rows = [{"col": i} for i in range(100)]
        entry = _make_db_entry(
            table_name="big",
            column_notes_json=json.dumps({"col": "note"}),
            sample_data_json=json.dumps(many_rows),
        )
        agent._insight_gen.analyze.return_value = []
        session = AsyncMock()

        await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        call_args = agent._insight_gen.analyze.call_args
        passed_rows = call_args[0][0]
        assert len(passed_rows) == 50

    @pytest.mark.asyncio
    async def test_multiple_raw_insights(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="t",
            column_notes_json=json.dumps({"a": "n"}),
            sample_data_json=json.dumps([{"a": 1}]),
        )
        agent._insight_gen.analyze.return_value = [
            {"type": "outlier", "title": "t1", "description": "d1", "confidence": 0.9},
            {"type": "summary", "title": "t2", "description": "d2", "confidence": 0.4},
        ]
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert len(result) == 2
        assert result[0]["type"] == "anomaly"
        assert result[1]["type"] == "observation"

    @pytest.mark.asyncio
    async def test_default_title_when_missing(self):
        agent = _make_agent()
        entry = _make_db_entry(
            table_name="t",
            column_notes_json=json.dumps({"a": "n"}),
            sample_data_json=json.dumps([{"a": 1}]),
        )
        agent._insight_gen.analyze.return_value = [
            {"type": "outlier", "description": "no title key", "confidence": 0.6},
        ]
        session = AsyncMock()

        result = await agent._analyze_table(
            session,
            "proj-1",
            "conn-1",
            entry,
        )

        assert result[0]["title"] == "[t] Pattern detected"


# ---------------------------------------------------------------------------
# run_scan
# ---------------------------------------------------------------------------


class TestRunScan:
    @pytest.mark.asyncio
    async def test_empty_tables_returns_zeros(self):
        agent = _make_agent()
        agent._load_db_index = AsyncMock(return_value=[])
        session = AsyncMock()

        result = await agent.run_scan(session, "proj-1", "conn-1")

        assert result.insights_created == 0
        assert result.insights_updated == 0
        assert result.queries_run == 0
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_provided_db_index_skips_load(self):
        agent = _make_agent()
        agent._load_db_index = AsyncMock()
        agent._analyze_table = AsyncMock(return_value=[])
        entry = _make_db_entry(table_name="t")
        session = AsyncMock()

        await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        agent._load_db_index.assert_not_awaited()
        agent._analyze_table.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_load_db_index(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._load_db_index = AsyncMock(return_value=[entry])
        agent._analyze_table = AsyncMock(return_value=[])
        session = AsyncMock()

        await agent.run_scan(session, "proj-1", "conn-1")

        agent._load_db_index.assert_awaited_once_with(session, "conn-1")

    @pytest.mark.asyncio
    async def test_insights_created_count(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {
                    "type": "trend",
                    "title": "x",
                    "description": "d",
                    "severity": "info",
                    "confidence": 0.5,
                },
            ]
        )
        record = MagicMock()
        record.times_surfaced = 1
        agent._memory.store_insight.return_value = record
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        assert result.insights_created == 1
        assert result.insights_updated == 0
        assert result.queries_run == 1

    @pytest.mark.asyncio
    async def test_insights_updated_count(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {"type": "trend", "title": "x", "description": "d"},
            ]
        )
        record = MagicMock()
        record.times_surfaced = 3
        agent._memory.store_insight.return_value = record
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        assert result.insights_created == 0
        assert result.insights_updated == 1

    @pytest.mark.asyncio
    async def test_mixed_created_and_updated(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {"type": "a", "title": "new", "description": "d1"},
                {"type": "b", "title": "old", "description": "d2"},
            ]
        )
        new_record = MagicMock(times_surfaced=1)
        old_record = MagicMock(times_surfaced=5)
        agent._memory.store_insight.side_effect = [new_record, old_record]
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        assert result.insights_created == 1
        assert result.insights_updated == 1

    @pytest.mark.asyncio
    async def test_exception_caught_and_added_to_errors(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="broken_table")
        agent._analyze_table = AsyncMock(side_effect=RuntimeError("db timeout"))
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        assert len(result.errors) == 1
        assert "db timeout" in result.errors[0]
        assert result.queries_run == 0

    @pytest.mark.asyncio
    async def test_exception_in_store_insight(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {"type": "trend", "title": "x", "description": "d"},
            ]
        )
        agent._memory.store_insight.side_effect = ValueError("bad type")
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        assert len(result.errors) == 1
        assert "bad type" in result.errors[0]

    @pytest.mark.asyncio
    async def test_multiple_tables_some_fail(self):
        agent = _make_agent()
        good_entry = _make_db_entry(table_name="good")
        bad_entry = _make_db_entry(table_name="bad")

        async def analyze_side_effect(_s, _p, _c, entry, **_kw):
            if entry.table_name == "bad":
                raise RuntimeError("fail")
            return [{"type": "t", "title": "ok", "description": "d"}]

        agent._analyze_table = AsyncMock(side_effect=analyze_side_effect)
        record = MagicMock(times_surfaced=1)
        agent._memory.store_insight.return_value = record
        session = AsyncMock()

        result = await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[good_entry, bad_entry],
        )

        assert result.insights_created == 1
        assert result.queries_run == 1
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_tables_capped_at_10(self):
        agent = _make_agent()
        entries = [_make_db_entry(table_name=f"t{i}") for i in range(15)]
        agent._analyze_table = AsyncMock(return_value=[])
        session = AsyncMock()

        await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=entries,
        )

        assert agent._analyze_table.await_count == 10

    @pytest.mark.asyncio
    async def test_store_insight_receives_correct_args(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {
                    "type": "anomaly",
                    "title": "[t] spike",
                    "description": "desc",
                    "severity": "warning",
                    "confidence": 0.85,
                    "action": "investigate",
                    "impact": "revenue",
                    "sample_size": 42,
                },
            ]
        )
        record = MagicMock(times_surfaced=1)
        agent._memory.store_insight.return_value = record
        session = AsyncMock()

        await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        agent._memory.store_insight.assert_awaited_once_with(
            session,
            "proj-1",
            "anomaly",
            "[t] spike",
            "desc",
            connection_id="conn-1",
            severity="warning",
            confidence=0.85,
            recommended_action="investigate",
            expected_impact="revenue",
            trust_validation_method="auto_scan",
            sample_size=42,
        )

    @pytest.mark.asyncio
    async def test_store_insight_default_optional_fields(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(
            return_value=[
                {"type": "trend", "title": "x", "description": "d"},
            ]
        )
        record = MagicMock(times_surfaced=1)
        agent._memory.store_insight.return_value = record
        session = AsyncMock()

        await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
        )

        call_kwargs = agent._memory.store_insight.call_args
        assert call_kwargs.kwargs["severity"] == "info"
        assert call_kwargs.kwargs["confidence"] == 0.5
        assert call_kwargs.kwargs["recommended_action"] == ""
        assert call_kwargs.kwargs["expected_impact"] == ""
        assert call_kwargs.kwargs["sample_size"] == 0

    @pytest.mark.asyncio
    async def test_passes_connector_and_llm_to_analyze(self):
        agent = _make_agent()
        entry = _make_db_entry(table_name="t")
        agent._analyze_table = AsyncMock(return_value=[])
        session = AsyncMock()
        connector = MagicMock()
        llm = MagicMock()

        await agent.run_scan(
            session,
            "proj-1",
            "conn-1",
            db_index_entries=[entry],
            connector=connector,
            llm=llm,
        )

        call_kwargs = agent._analyze_table.call_args.kwargs
        assert call_kwargs["connector"] is connector
        assert call_kwargs["llm"] is llm


# ---------------------------------------------------------------------------
# _load_db_index
# ---------------------------------------------------------------------------


class TestLoadDbIndex:
    @pytest.mark.asyncio
    async def test_queries_active_entries(self):
        agent = _make_agent()
        mock_entry = MagicMock()
        session = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [mock_entry]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute.return_value = execute_result

        result = await agent._load_db_index(session, "conn-1")

        session.execute.assert_awaited_once()
        assert result == [mock_entry]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_entries(self):
        agent = _make_agent()
        session = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute.return_value = execute_result

        result = await agent._load_db_index(session, "conn-1")

        assert result == []


# ---------------------------------------------------------------------------
# _llm_deep_analysis
# ---------------------------------------------------------------------------


class TestLlmDeepAnalysis:
    @pytest.mark.asyncio
    async def test_returns_parsed_insights(self):
        agent = _make_agent()
        llm = AsyncMock()
        response_content = json.dumps(
            [
                {
                    "type": "opportunity",
                    "title": "High value segment",
                    "description": "Top customers spend 5x more",
                    "severity": "info",
                    "confidence": 0.9,
                    "action": "target this segment",
                    "impact": "revenue increase",
                },
            ]
        )
        llm.complete.return_value = MagicMock(content=response_content)

        sample = [{"amount": 100}, {"amount": 200}, {"amount": 300}]
        result = await agent._llm_deep_analysis(
            "orders",
            {"amount": "total"},
            sample,
            llm,
        )

        assert len(result) == 1
        assert result[0]["title"] == "[orders] High value segment"
        assert result[0]["confidence"] <= 0.7
        # T05 — sample_size must count rows, NOT response-text length.
        assert result[0]["sample_size"] == len(sample)

    @pytest.mark.asyncio
    async def test_sample_size_zero_when_no_rows(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(
            content=json.dumps(
                [{"type": "trend", "title": "t", "confidence": 0.5}]
            )
        )

        result = await agent._llm_deep_analysis("t", {"c": "n"}, [], llm)
        assert result and result[0]["sample_size"] == 0


    @pytest.mark.asyncio
    async def test_caps_confidence_at_07(self):
        agent = _make_agent()
        llm = AsyncMock()
        response_content = json.dumps(
            [
                {"type": "trend", "title": "t1", "confidence": 0.95},
            ]
        )
        llm.complete.return_value = MagicMock(content=response_content)

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result[0]["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_json_response(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(content="No insights found.")

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.side_effect = RuntimeError("LLM down")

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_response_is_none(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.return_value = None

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_content_is_none(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(content=None)

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_skips_items_without_title(self):
        agent = _make_agent()
        llm = AsyncMock()
        response_content = json.dumps(
            [
                {"type": "trend", "description": "no title"},
                {"type": "trend", "title": "has title"},
            ]
        )
        llm.complete.return_value = MagicMock(content=response_content)

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert len(result) == 1
        assert "has title" in result[0]["title"]

    @pytest.mark.asyncio
    async def test_limits_to_5_insights(self):
        agent = _make_agent()
        llm = AsyncMock()
        items = [{"type": "t", "title": f"insight-{i}"} for i in range(10)]
        llm.complete.return_value = MagicMock(content=json.dumps(items))

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_list_json(self):
        agent = _make_agent()
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(content='{"not": "a list"}')

        result = await agent._llm_deep_analysis(
            "tbl",
            {"c": "n"},
            [{"c": 1}],
            llm,
        )

        assert result == []
