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
        assert "execute_query" in prompt
        assert "search_knowledge" in prompt
        assert "get_schema_info" in prompt
        assert "get_custom_rules" in prompt
        assert "postgres" in prompt.lower()

    def test_no_connection_excludes_db_tools(self):
        prompt = build_agent_system_prompt(
            project_name="Demo",
            has_connection=False,
            has_knowledge_base=True,
        )
        assert "execute_query" not in prompt
        assert "get_schema_info" not in prompt
        assert "search_knowledge" in prompt

    def test_no_knowledge_excludes_search(self):
        prompt = build_agent_system_prompt(
            db_type="mysql",
            has_connection=True,
            has_knowledge_base=False,
        )
        assert "search_knowledge" not in prompt
        assert "execute_query" in prompt

    def test_no_capabilities(self):
        prompt = build_agent_system_prompt(
            has_connection=False,
            has_knowledge_base=False,
        )
        assert "general conversation" in prompt.lower()
        assert "execute_query" not in prompt
        assert "search_knowledge" not in prompt

    def test_dialect_hints_mysql(self):
        prompt = build_agent_system_prompt(
            db_type="mysql",
            has_connection=True,
        )
        assert "backtick" in prompt.lower()

    def test_dialect_hints_clickhouse(self):
        prompt = build_agent_system_prompt(
            db_type="clickhouse",
            has_connection=True,
        )
        assert "ClickHouse" in prompt

    def test_dialect_hints_mongodb(self):
        prompt = build_agent_system_prompt(
            db_type="mongodb",
            has_connection=True,
        )
        assert "JSON query spec" in prompt

    def test_no_project_name(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "project" not in prompt.split("\n")[0] or "AI data assistant" in prompt

    def test_re_visualization_section_when_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "RE-VISUALIZATION:" in prompt
        assert "pie chart" in prompt.lower()
        assert "[Context]" in prompt

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
        assert "DATABASE TABLES:" in prompt
        assert "orders(~125K" in prompt
        assert "users(~50K" in prompt

    def test_empty_table_map_not_injected(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            has_db_index=True,
            db_type="postgres",
            table_map="",
        )
        assert "DATABASE TABLES:" not in prompt

    def test_query_context_tool_mentioned_with_db_index(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            has_db_index=True,
            db_type="postgres",
        )
        assert "get_query_context" in prompt

    def test_manage_rules_capability_with_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "manage_custom_rules" in prompt
        assert "Rules Management" in prompt

    def test_manage_rules_guideline_with_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "remember, save, or create" in prompt

    def test_manage_rules_absent_without_connection(self):
        prompt = build_agent_system_prompt(
            has_connection=False,
            has_knowledge_base=True,
        )
        assert "manage_custom_rules" not in prompt
