"""Unit tests for app.core.tools get_sql_tools function."""

from app.core.tools import get_available_tools


class TestGetAvailableTools:
    def test_no_connection(self):
        tools = get_available_tools(has_connection=False)
        assert len(tools) == 0

    def test_connection_only(self):
        tools = get_available_tools(has_connection=True)
        names = [t.name for t in tools]
        assert "execute_query" in names
        assert "get_schema_info" in names
        assert "get_query_context" not in names

    def test_with_db_index(self):
        tools = get_available_tools(has_connection=True, has_db_index=True)
        names = [t.name for t in tools]
        assert "get_query_context" in names
        assert "get_db_index" in names

    def test_with_learnings(self):
        tools = get_available_tools(has_connection=True, has_learnings=True)
        names = [t.name for t in tools]
        assert "get_agent_learnings" in names

    def test_with_code_db_sync(self):
        tools = get_available_tools(has_connection=True, has_code_db_sync=True)
        names = [t.name for t in tools]
        assert "get_sync_context" in names

    def test_with_knowledge_base(self):
        tools = get_available_tools(has_knowledge_base=True)
        names = [t.name for t in tools]
        assert "search_knowledge" in names
        assert "get_entity_info" in names

    def test_all_flags(self):
        tools = get_available_tools(
            has_connection=True,
            has_db_index=True,
            has_knowledge_base=True,
            has_code_db_sync=True,
            has_learnings=True,
        )
        names = [t.name for t in tools]
        assert "execute_query" in names
        assert "get_query_context" in names
        assert "get_agent_learnings" in names
        assert "get_sync_context" in names
        assert "search_knowledge" in names
