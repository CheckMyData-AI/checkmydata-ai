"""Tests for the prompt builder (now delegates to orchestrator prompt).

These tests verify the orchestrator system prompt produced by
``build_agent_system_prompt``.  After the multi-agent refactor the
orchestrator prompt references *meta-tools* (query_database,
search_codebase, manage_rules) rather than the raw SQL-level tools
(execute_query, get_schema_info, etc.).
"""

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

    def test_re_visualization_section_when_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "RE-VISUALIZATION:" in prompt
        assert "pie chart" in prompt.lower() or "chart" in prompt.lower()

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
