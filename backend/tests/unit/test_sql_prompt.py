"""Unit tests for SQL prompt builder."""

from app.agents.prompts.sql_prompt import DIALECT_HINTS, build_sql_system_prompt


class TestDialectHints:
    def test_mysql_exists(self):
        assert "mysql" in DIALECT_HINTS
        assert "backtick" in DIALECT_HINTS["mysql"]

    def test_postgres_exists(self):
        assert "postgres" in DIALECT_HINTS
        assert "double-quote" in DIALECT_HINTS["postgres"]

    def test_clickhouse_exists(self):
        assert "clickhouse" in DIALECT_HINTS

    def test_mongodb_exists(self):
        assert "mongodb" in DIALECT_HINTS


class TestBuildSqlSystemPrompt:
    def test_basic_prompt_no_flags(self):
        prompt = build_sql_system_prompt()
        assert "expert SQL query agent" in prompt
        assert "get_schema_info" in prompt

    def test_with_db_index(self):
        prompt = build_sql_system_prompt(has_db_index=True)
        assert "get_query_context" in prompt

    def test_with_db_index_stale(self):
        prompt = build_sql_system_prompt(has_db_index=True, db_index_stale=True)
        assert "WARNING" in prompt
        assert "older than" in prompt

    def test_with_code_db_sync(self):
        prompt = build_sql_system_prompt(has_code_db_sync=True)
        assert "get_sync_context" in prompt

    def test_with_learnings(self):
        prompt = build_sql_system_prompt(has_learnings=True)
        assert "get_agent_learnings" in prompt

    def test_with_current_datetime(self):
        prompt = build_sql_system_prompt(current_datetime="2026-03-22T12:00:00")
        assert "2026-03-22" in prompt

    def test_with_table_map(self):
        prompt = build_sql_system_prompt(table_map="users, orders, products")
        assert "users, orders, products" in prompt
        assert "DATABASE TABLES" in prompt

    def test_with_learnings_prompt(self):
        prompt = build_sql_system_prompt(learnings_prompt="Previous learnings here")
        assert "Previous learnings here" in prompt

    def test_with_notes_prompt(self):
        prompt = build_sql_system_prompt(notes_prompt="Session notes here")
        assert "Session notes here" in prompt

    def test_with_db_type_postgres(self):
        prompt = build_sql_system_prompt(db_type="postgres")
        assert "SQL DIALECT (postgres)" in prompt
        assert "double-quote" in prompt

    def test_with_db_type_mysql(self):
        prompt = build_sql_system_prompt(db_type="mysql")
        assert "SQL DIALECT (mysql)" in prompt

    def test_with_unknown_db_type(self):
        prompt = build_sql_system_prompt(db_type="oracle")
        assert "SQL DIALECT" not in prompt

    def test_with_sync_conventions(self):
        prompt = build_sql_system_prompt(
            sync_conventions="Use ISO date format",
            sync_critical_warnings="Never use raw SQL dates",
        )
        assert "CRITICAL DATA FORMAT RULES" in prompt
        assert "Use ISO date format" in prompt
        assert "Never use raw SQL dates" in prompt

    def test_with_required_filters(self):
        prompt = build_sql_system_prompt(required_filters="WHERE is_active = true")
        assert "REQUIRED QUERY FILTERS" in prompt
        assert "WHERE is_active = true" in prompt

    def test_with_column_value_mappings(self):
        prompt = build_sql_system_prompt(column_value_mappings="status: 1=active, 2=inactive")
        assert "COLUMN VALUE MEANINGS" in prompt
        assert "status: 1=active, 2=inactive" in prompt

    def test_current_question_focus_directive(self):
        prompt = build_sql_system_prompt()
        assert "CURRENT QUESTION FOCUS" in prompt
        assert "do not treat prior queries" in prompt

    def test_all_options_combined(self):
        prompt = build_sql_system_prompt(
            db_type="postgres",
            has_db_index=True,
            db_index_stale=True,
            has_code_db_sync=True,
            has_learnings=True,
            table_map="users, orders",
            learnings_prompt="Some learnings",
            sync_conventions="ISO dates",
            sync_critical_warnings="Watch out",
            current_datetime="2026-01-01",
            notes_prompt="Notes here",
            required_filters="status = active",
            column_value_mappings="type: 1=A",
        )
        assert "expert SQL query agent" in prompt
        assert "get_query_context" in prompt
        assert "WARNING" in prompt
        assert "get_sync_context" in prompt
        assert "get_agent_learnings" in prompt
        assert "DATABASE TABLES" in prompt
        assert "CRITICAL DATA FORMAT RULES" in prompt
        assert "REQUIRED QUERY FILTERS" in prompt
        assert "COLUMN VALUE MEANINGS" in prompt
        assert "SQL DIALECT (postgres)" in prompt


class TestPlannerPrompt:
    def test_build_with_db_type(self):
        from app.agents.prompts.planner_prompt import build_planner_user_prompt

        result = build_planner_user_prompt("What is revenue?", db_type="postgres")
        assert "Database type: postgres" in result
        assert "User question:" in result

    def test_build_minimal(self):
        from app.agents.prompts.planner_prompt import build_planner_user_prompt

        result = build_planner_user_prompt("test?")
        assert "Database type" not in result
        assert "Available tables" not in result
