"""Tests for the prompt builder (now delegates to orchestrator prompt).

These tests verify the orchestrator system prompt produced by
``build_agent_system_prompt``.  After the multi-agent refactor the
orchestrator prompt references *meta-tools* (query_database,
search_codebase, manage_rules) rather than the raw SQL-level tools
(execute_query, get_schema_info, etc.).
"""

from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.knowledge_prompt import build_knowledge_system_prompt
from app.agents.prompts.mcp_prompt import build_mcp_source_system_prompt
from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt
from app.agents.prompts.sql_prompt import build_sql_system_prompt
from app.agents.prompts.viz_prompt import build_viz_system_prompt
from app.core.prompt_builder import build_agent_system_prompt


class TestBuildAgentSystemPrompt:
    def test_full_capabilities(self):
        prompt = build_agent_system_prompt(
            project_name="Acme",
            db_type="postgres",
            has_connection=True,
            has_knowledge_base=True,
        )
        assert 'project "Acme"' in prompt
        assert "query_database" in prompt
        assert "search_codebase" in prompt
        assert "postgres" in prompt.lower()

    def test_no_connection_excludes_db_tools(self):
        prompt = build_agent_system_prompt(
            project_name="Demo",
            has_connection=False,
            has_knowledge_base=True,
        )
        assert "query_database" not in prompt
        assert "search_codebase" in prompt

    def test_no_knowledge_excludes_search(self):
        prompt = build_agent_system_prompt(
            db_type="mysql",
            has_connection=True,
            has_knowledge_base=False,
        )
        assert "search_codebase" not in prompt
        assert "query_database" in prompt

    def test_no_capabilities(self):
        prompt = build_agent_system_prompt(
            has_connection=False,
            has_knowledge_base=False,
        )
        assert "general conversation" in prompt.lower()
        assert "query_database" not in prompt
        assert "search_codebase" not in prompt

    def test_no_project_name(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "AI data assistant" in prompt

    def test_principles_section_when_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "PRINCIPLES:" in prompt

    def test_no_re_visualization_without_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=False,
            has_knowledge_base=True,
        )
        assert "RE-VISUALIZATION:" not in prompt

    def test_table_map_injected(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            has_db_index=True,
            db_type="postgres",
            table_map="orders(~125K, customer orders), users(~50K, user accounts)",
        )
        assert "DATABASE TABLES" in prompt
        assert "orders(~125K" in prompt
        assert "users(~50K" in prompt

    def test_empty_table_map_not_injected(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            has_db_index=True,
            db_type="postgres",
            table_map="",
        )
        assert "DATABASE TABLES" not in prompt

    def test_manage_rules_capability_with_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "manage_rules" in prompt

    def test_manage_rules_guideline_with_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        low = prompt.lower()
        assert "remember" in low or "save" in low or "guideline" in low

    def test_manage_rules_absent_without_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=False,
            has_knowledge_base=True,
        )
        assert "manage_rules" not in prompt

    def test_datetime_injected_via_deprecated_builder(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "Current date/time:" in prompt
        assert "UTC" in prompt


class TestOrchestratorDatetime:
    def test_datetime_present_when_provided(self):
        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            current_datetime="2026-03-19 14:30 UTC (Thursday)",
        )
        assert "2026-03-19 14:30 UTC (Thursday)" in prompt
        assert "Current date/time:" in prompt

    def test_datetime_absent_when_none(self):
        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "Current date/time:" not in prompt


class TestSqlDatetime:
    def test_datetime_present_when_provided(self):
        prompt = build_sql_system_prompt(
            db_type="mysql",
            current_datetime="2026-03-19 14:30 UTC (Thursday)",
        )
        assert "2026-03-19 14:30 UTC (Thursday)" in prompt
        assert "relative date calculations" in prompt

    def test_datetime_absent_when_none(self):
        prompt = build_sql_system_prompt(db_type="mysql")
        assert "Current date/time:" not in prompt


class TestKnowledgeDatetime:
    def test_datetime_present(self):
        prompt = build_knowledge_system_prompt(
            current_datetime="2026-03-19 14:30 UTC (Thursday)",
        )
        assert "2026-03-19 14:30 UTC (Thursday)" in prompt

    def test_datetime_absent(self):
        prompt = build_knowledge_system_prompt()
        assert "Current date/time:" not in prompt

    def test_contains_workflow(self):
        prompt = build_knowledge_system_prompt()
        assert "search_knowledge" in prompt


class TestVizDatetime:
    def test_datetime_present(self):
        prompt = build_viz_system_prompt(
            current_datetime="2026-03-19 14:30 UTC (Thursday)",
        )
        assert "2026-03-19 14:30 UTC (Thursday)" in prompt

    def test_datetime_absent(self):
        prompt = build_viz_system_prompt()
        assert "Current date/time:" not in prompt

    def test_contains_rules(self):
        prompt = build_viz_system_prompt()
        assert "bar_chart" in prompt
        assert "recommend_visualization" in prompt


class TestMcpDatetime:
    def test_datetime_present(self):
        prompt = build_mcp_source_system_prompt(
            source_name="TestSource",
            current_datetime="2026-03-19 14:30 UTC (Thursday)",
        )
        assert "2026-03-19 14:30 UTC (Thursday)" in prompt
        assert "TestSource" in prompt

    def test_datetime_absent(self):
        prompt = build_mcp_source_system_prompt(source_name="Test")
        assert "Current date/time:" not in prompt


class TestGetCurrentDatetimeStr:
    def test_returns_utc_string(self):
        result = get_current_datetime_str()
        assert "UTC" in result
        assert "202" in result


class TestOrchestratorRecentLearnings:
    def test_learnings_injected(self):
        from app.agents.prompts.orchestrator_prompt import (
            build_orchestrator_system_prompt,
        )

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            recent_learnings="- Prefer joins on user_id",
        )
        assert "Prefer joins on user_id" in prompt
        assert "verified patterns" in prompt
