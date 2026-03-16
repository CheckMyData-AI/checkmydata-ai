from app.core.query_builder import _build_system_prompt


class TestDialectAwarePrompt:
    def test_mysql_prompt_has_backtick_hint(self):
        prompt = _build_system_prompt("mysql")
        assert "backtick" in prompt
        assert "mysql" in prompt

    def test_postgres_prompt_has_double_quote_hint(self):
        prompt = _build_system_prompt("postgres")
        assert "double-quote" in prompt

    def test_clickhouse_prompt_has_approximate_hint(self):
        prompt = _build_system_prompt("clickhouse")
        assert "approximate" in prompt
        assert "uniq()" in prompt

    def test_mongodb_prompt_has_json_spec(self):
        prompt = _build_system_prompt("mongodb")
        assert "JSON query spec" in prompt

    def test_unknown_db_type_fallback(self):
        prompt = _build_system_prompt("oracle")
        assert "Standard SQL" in prompt

    def test_all_prompts_have_join_guidance(self):
        for db_type in ["mysql", "postgres", "clickhouse"]:
            prompt = _build_system_prompt(db_type)
            assert "JOIN" in prompt
            assert "Foreign Key" in prompt
            assert "index" in prompt.lower()
