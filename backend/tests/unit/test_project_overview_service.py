"""Unit tests for ProjectOverviewService."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.project_overview_service import ProjectOverviewService, _hash_section


@pytest.fixture
def svc():
    return ProjectOverviewService()


def _mock_session_factory():
    """Create a mock AsyncSession that returns configurable results."""
    session = AsyncMock()
    _execute_results = []

    async def _execute(stmt):
        if _execute_results:
            return _execute_results.pop(0)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        result.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session, _execute_results


class TestBuildDbSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, svc):
        session, results = _mock_session_factory()

        summary_result = MagicMock()
        summary_result.scalars.return_value.all.return_value = []
        results.append(summary_result)

        idx_result = MagicMock()
        idx_result.scalars.return_value.all.return_value = []
        results.append(idx_result)

        section = await svc._build_db_section(session, ["conn-1"])
        assert section == ""

    @pytest.mark.asyncio
    async def test_includes_table_info(self, svc):
        session, results = _mock_session_factory()

        summary = MagicMock()
        summary.total_tables = 10
        summary.active_tables = 8
        summary.empty_tables = 2
        summary_result = MagicMock()
        summary_result.scalars.return_value.all.return_value = [summary]
        results.append(summary_result)

        table = MagicMock()
        table.table_name = "orders"
        table.row_count = 5000
        table.relevance_score = 5
        table.business_description = "Customer orders table"
        table.column_distinct_values_json = json.dumps({"status": ["active", "cancelled"]})
        idx_result = MagicMock()
        idx_result.scalars.return_value.all.return_value = [table]
        results.append(idx_result)

        section = await svc._build_db_section(session, ["conn-1"])
        assert "Database Structure" in section
        assert "orders" in section
        assert "5,000" in section
        assert "status" in section
        assert "active" in section


class TestBuildSyncSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_sync(self, svc):
        session, results = _mock_session_factory()

        sum_result = MagicMock()
        sum_result.scalars.return_value.all.return_value = []
        results.append(sum_result)

        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = []
        results.append(sync_result)

        section = await svc._build_sync_section(session, ["conn-1"])
        assert section == ""

    @pytest.mark.asyncio
    async def test_includes_filters_and_mappings(self, svc):
        session, results = _mock_session_factory()

        summary = MagicMock()
        summary.data_conventions = "Amounts stored in cents"
        summary.query_guidelines = "Always use UTC timestamps"
        sum_result = MagicMock()
        sum_result.scalars.return_value.all.return_value = [summary]
        results.append(sum_result)

        sync_entry = MagicMock()
        sync_entry.table_name = "transactions"
        sync_entry.required_filters_json = json.dumps({"processed": "= 1"})
        sync_entry.column_value_mappings_json = json.dumps({"status": "0=pending, 1=done"})
        sync_entry.conversion_warnings = "Divide by 100 for dollars"
        sync_entry.confidence_score = 4
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = [sync_entry]
        results.append(sync_result)

        section = await svc._build_sync_section(session, ["conn-1"])
        assert "Data Conventions" in section
        assert "Amounts stored in cents" in section
        assert "Required filters" in section
        assert "processed" in section
        assert "Column value mappings" in section
        assert "0=pending" in section


class TestBuildRulesSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_rules(self, svc):
        session, results = _mock_session_factory()

        rule_result = MagicMock()
        rule_result.scalars.return_value.all.return_value = []
        results.append(rule_result)

        section = await svc._build_rules_section(session, "proj-1")
        assert section == ""

    @pytest.mark.asyncio
    async def test_includes_rules(self, svc):
        session, results = _mock_session_factory()

        rule = MagicMock()
        rule.name = "Revenue Calculation"
        rule.content = "Always divide amounts by 100 to convert cents to dollars."
        rule_result = MagicMock()
        rule_result.scalars.return_value.all.return_value = [rule]
        results.append(rule_result)

        section = await svc._build_rules_section(session, "proj-1")
        assert "Custom Rules" in section
        assert "Revenue Calculation" in section
        assert "Always divide" in section


class TestBuildLearningsSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_learnings(self, svc):
        session, results = _mock_session_factory()

        count_result = MagicMock()
        count_result.all.return_value = []
        results.append(count_result)

        section = await svc._build_learnings_section(session, ["conn-1"])
        assert section == ""

    @pytest.mark.asyncio
    async def test_includes_learnings(self, svc):
        session, results = _mock_session_factory()

        count_result = MagicMock()
        count_result.all.return_value = [("query_fix", 3), ("schema_note", 2)]
        results.append(count_result)

        learning = MagicMock()
        learning.category = "query_fix"
        learning.lesson = "Always filter by is_active=1 for users table"
        learning.confidence = 0.9
        top_result = MagicMock()
        top_result.scalars.return_value.all.return_value = [learning]
        results.append(top_result)

        section = await svc._build_learnings_section(session, ["conn-1"])
        assert "Agent Learnings" in section
        assert "query_fix: 3" in section
        assert "Always filter" in section


class TestBuildProfileSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_profile(self, svc):
        session, results = _mock_session_factory()

        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = None
        results.append(cache_result)

        section = await svc._build_profile_section(session, "proj-1")
        assert section == ""

    @pytest.mark.asyncio
    async def test_includes_profile(self, svc):
        session, results = _mock_session_factory()

        cache = MagicMock()
        cache.profile_json = json.dumps(
            {
                "primary_language": "Python",
                "frameworks": ["Django", "FastAPI"],
                "orms": ["SQLAlchemy"],
                "key_directories": {"models": "app/models", "api": "app/api"},
            }
        )
        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = cache
        results.append(cache_result)

        section = await svc._build_profile_section(session, "proj-1")
        assert "Repository Profile" in section
        assert "Python" in section
        assert "Django" in section
        assert "SQLAlchemy" in section


class TestGenerateOverview:
    @pytest.mark.asyncio
    async def test_empty_when_no_connections(self, svc):
        session, results = _mock_session_factory()

        conn_result = MagicMock()
        conn_result.scalars.return_value.all.return_value = []
        results.append(conn_result)

        overview = await svc.generate_overview(session, "proj-1")
        assert overview == ""

    @pytest.mark.asyncio
    async def test_with_connection_id(self, svc):
        session = AsyncMock()

        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None
        empty_result.scalars.return_value.all.return_value = []
        empty_result.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        overview = await svc.generate_overview(session, "proj-1", connection_id="conn-1")
        assert isinstance(overview, str)


class TestSplitOverviewSections:
    def test_empty_string(self):
        result = ProjectOverviewService._split_overview_sections("")
        assert result == {}

    def test_single_section(self):
        overview = "## Database Structure\n- orders (5000 rows)\n- users (100 rows)"
        result = ProjectOverviewService._split_overview_sections(overview)
        assert "db" in result
        assert "orders" in result["db"]

    def test_multiple_sections(self):
        overview = (
            "## Database Structure\n- orders\n\n"
            "## Custom Rules (2)\n- Rule A\n\n"
            "## Agent Learnings\nTotal: 5"
        )
        result = ProjectOverviewService._split_overview_sections(overview)
        assert "db" in result
        assert "rules" in result
        assert "learnings" in result
        assert len(result) == 3

    def test_all_six_sections(self):
        overview = (
            "## Database Structure\ndb content\n"
            "## Data Conventions\nsync content\n"
            "## Custom Rules\nrules content\n"
            "## Agent Learnings\nlearnings content\n"
            "## Session Notes\nnotes content\n"
            "## Repository Profile\nprofile content"
        )
        result = ProjectOverviewService._split_overview_sections(overview)
        assert set(result.keys()) == {"db", "sync", "rules", "learnings", "notes", "profile"}

    def test_preamble_before_first_header_ignored(self):
        overview = "Some preamble text\n## Database Structure\n- orders"
        result = ProjectOverviewService._split_overview_sections(overview)
        assert "db" in result
        assert "preamble" not in result["db"]


class TestHashSection:
    def test_deterministic(self):
        text = "## Database Structure\n- orders (5000 rows)"
        assert _hash_section(text) == _hash_section(text)

    def test_different_input_different_hash(self):
        assert _hash_section("abc") != _hash_section("xyz")

    def test_empty_string(self):
        result = _hash_section("")
        assert isinstance(result, str) and len(result) == 32


class TestBuildNotesSection:
    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, svc):
        session, results = _mock_session_factory()

        note_result = MagicMock()
        note_result.all.return_value = []
        results.append(note_result)

        bench_result = MagicMock()
        bench_result.scalars.return_value.all.return_value = []
        results.append(bench_result)

        section = await svc._build_notes_section(session, "proj-1", ["conn-1"])
        assert section == ""

    @pytest.mark.asyncio
    async def test_only_notes(self, svc):
        session, results = _mock_session_factory()

        note_result = MagicMock()
        note_result.all.return_value = [("correction", 3), ("tip", 2)]
        results.append(note_result)

        bench_result = MagicMock()
        bench_result.scalars.return_value.all.return_value = []
        results.append(bench_result)

        section = await svc._build_notes_section(session, "proj-1", ["conn-1"])
        assert "Session Notes" in section
        assert "correction: 3" in section

    @pytest.mark.asyncio
    async def test_only_benchmarks(self, svc):
        session, results = _mock_session_factory()

        note_result = MagicMock()
        note_result.all.return_value = []
        results.append(note_result)

        bench = MagicMock()
        bench.metric_key = "monthly_revenue"
        bench.value = 120000
        bench.unit = "USD"
        bench.times_confirmed = 3
        bench_result = MagicMock()
        bench_result.scalars.return_value.all.return_value = [bench]
        results.append(bench_result)

        section = await svc._build_notes_section(session, "proj-1", ["conn-1"])
        assert "Verified benchmarks" in section
        assert "monthly_revenue" in section
        assert "USD" in section

    @pytest.mark.asyncio
    async def test_benchmark_without_unit(self, svc):
        session, results = _mock_session_factory()

        note_result = MagicMock()
        note_result.all.return_value = []
        results.append(note_result)

        bench = MagicMock()
        bench.metric_key = "user_count"
        bench.value = 5000
        bench.unit = None
        bench.times_confirmed = 2
        bench_result = MagicMock()
        bench_result.scalars.return_value.all.return_value = [bench]
        results.append(bench_result)

        section = await svc._build_notes_section(session, "proj-1", ["conn-1"])
        assert "user_count: 5000" in section
        assert "USD" not in section


class TestBuildProfileEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_profile_json(self, svc):
        session, results = _mock_session_factory()

        cache = MagicMock()
        cache.profile_json = "NOT-JSON"
        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = cache
        results.append(cache_result)

        section = await svc._build_profile_section(session, "proj-1")
        assert section == ""

    @pytest.mark.asyncio
    async def test_profile_with_only_key_dirs(self, svc):
        session, results = _mock_session_factory()

        cache = MagicMock()
        cache.profile_json = json.dumps(
            {
                "key_directories": {"models": "app/models", "api": "app/api"},
            }
        )
        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = cache
        results.append(cache_result)

        section = await svc._build_profile_section(session, "proj-1")
        assert "Key dirs" in section
        assert "models" in section


class TestBuildDbEdgeCases:
    @pytest.mark.asyncio
    async def test_table_without_row_count(self, svc):
        session, results = _mock_session_factory()

        summary_result = MagicMock()
        summary_result.scalars.return_value.all.return_value = []
        results.append(summary_result)

        table = MagicMock()
        table.table_name = "empty_table"
        table.row_count = None
        table.relevance_score = 2
        table.business_description = None
        table.column_distinct_values_json = None
        idx_result = MagicMock()
        idx_result.scalars.return_value.all.return_value = [table]
        results.append(idx_result)

        section = await svc._build_db_section(session, ["conn-1"])
        assert "empty_table" in section
        assert "?" in section

    @pytest.mark.asyncio
    async def test_table_with_invalid_distinct_json(self, svc):
        session, results = _mock_session_factory()

        summary_result = MagicMock()
        summary_result.scalars.return_value.all.return_value = []
        results.append(summary_result)

        table = MagicMock()
        table.table_name = "bad_json_table"
        table.row_count = 100
        table.relevance_score = 3
        table.business_description = "A table"
        table.column_distinct_values_json = "NOT-JSON"
        idx_result = MagicMock()
        idx_result.scalars.return_value.all.return_value = [table]
        results.append(idx_result)

        section = await svc._build_db_section(session, ["conn-1"])
        assert "bad_json_table" in section

    @pytest.mark.asyncio
    async def test_empty_connection_ids(self, svc):
        session, _ = _mock_session_factory()
        section = await svc._build_db_section(session, [])
        assert section == ""


class TestBuildSyncEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_filters_json_skipped(self, svc):
        session, results = _mock_session_factory()

        sum_result = MagicMock()
        sum_result.scalars.return_value.all.return_value = []
        results.append(sum_result)

        sync_entry = MagicMock()
        sync_entry.table_name = "bad_table"
        sync_entry.required_filters_json = "NOT-JSON"
        sync_entry.column_value_mappings_json = "NOT-JSON"
        sync_entry.conversion_warnings = "Watch out!"
        sync_entry.confidence_score = 3
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = [sync_entry]
        results.append(sync_result)

        section = await svc._build_sync_section(session, ["conn-1"])
        assert "Watch out!" in section

    @pytest.mark.asyncio
    async def test_empty_connection_ids(self, svc):
        session, _ = _mock_session_factory()
        section = await svc._build_sync_section(session, [])
        assert section == ""


class TestSaveOverview:
    @pytest.mark.asyncio
    async def test_no_connections_clears_cache(self, svc):
        session, results = _mock_session_factory()

        cache = MagicMock()
        cache.overview_text = "old overview"
        cache.section_hashes_json = "{}"
        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = cache
        results.append(cache_result)

        conn_result = MagicMock()
        conn_result.scalars.return_value.all.return_value = []
        results.append(conn_result)

        overview = await svc.save_overview(session, "proj-1")
        assert overview == ""
        assert cache.overview_text == ""
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_connections_no_cache(self, svc):
        session, results = _mock_session_factory()

        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = None
        results.append(cache_result)

        conn_result = MagicMock()
        conn_result.scalars.return_value.all.return_value = []
        results.append(conn_result)

        overview = await svc.save_overview(session, "proj-1")
        assert overview == ""

    @pytest.mark.asyncio
    async def test_creates_cache_when_missing(self, svc):
        session = AsyncMock()
        call_count = {"n": 0}

        async def _controlled_execute(stmt):
            idx = call_count["n"]
            call_count["n"] += 1
            r = MagicMock()
            if idx == 0:
                r.scalar_one_or_none.return_value = None
            elif idx == 1:
                r.scalars.return_value.all.return_value = ["conn-1"]
            else:
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_controlled_execute)
        session.commit = AsyncMock()
        session.add = MagicMock()

        overview = await svc.save_overview(session, "proj-1")
        assert isinstance(overview, str)
        session.add.assert_called_once()
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_section_hashes_json(self, svc):
        session, results = _mock_session_factory()

        cache = MagicMock()
        cache.overview_text = ""
        cache.section_hashes_json = "NOT-JSON"
        cache_result = MagicMock()
        cache_result.scalar_one_or_none.return_value = cache
        results.append(cache_result)

        conn_result = MagicMock()
        conn_result.scalars.return_value.all.return_value = ["conn-1"]
        results.append(conn_result)

        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None
        empty_result.scalars.return_value.all.return_value = []
        empty_result.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        overview = await svc.save_overview(session, "proj-1")
        assert isinstance(overview, str)
        session.commit.assert_awaited()


class TestGenerateOverviewTruncation:
    @pytest.mark.asyncio
    async def test_truncation_applied(self, svc):
        session = AsyncMock()
        call_count = {"n": 0}

        async def _controlled_execute(stmt):
            call_count["n"] += 1
            r = MagicMock()
            stmt_str = str(stmt)
            if "custom_rule" in stmt_str.lower():
                rule = MagicMock()
                rule.name = "BigRule"
                rule.content = "x" * 10000
                r.scalars.return_value.all.return_value = [rule] * 50
                r.all.return_value = []
            else:
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = []
                r.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_controlled_execute)

        overview = await svc.generate_overview(session, "proj-1", connection_id="conn-1")
        assert len(overview) <= 6000 + len("\n...(truncated)") + 10


class TestOrchestratorPromptIntegration:
    def test_overview_injected_into_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            project_name="TestProject",
            db_type="postgres",
            has_connection=True,
            has_knowledge_base=False,
            project_overview="## Database Structure\n- orders (5000 rows)",
        )
        assert "PROJECT KNOWLEDGE OVERVIEW" in prompt
        assert "Database Structure" in prompt
        assert "orders" in prompt

    def test_no_overview_when_none(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            project_name="TestProject",
            db_type="postgres",
            has_connection=True,
            has_knowledge_base=False,
            project_overview=None,
        )
        assert "PROJECT KNOWLEDGE OVERVIEW" not in prompt
