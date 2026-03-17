from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import (
    ColumnInfo,
    ConnectionConfig,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.core.tool_executor import ToolExecutor
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import ToolCall


@pytest.fixture
def config():
    return ConnectionConfig(
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
    )


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_step(wf_id, step, detail=""):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    return vs


@pytest.fixture
def mock_schema_indexer():
    return MagicMock()


@pytest.fixture
def mock_rules_engine():
    r = MagicMock()
    r.load_rules = MagicMock(return_value=[])
    r.load_db_rules = AsyncMock(return_value=[])
    r.rules_to_context = MagicMock(return_value="")
    return r


@pytest.fixture
def executor(
    config, mock_llm, mock_vector_store, mock_schema_indexer, mock_rules_engine, mock_tracker
):
    return ToolExecutor(
        project_id="proj-1",
        connection_config=config,
        llm_router=mock_llm,
        vector_store=mock_vector_store,
        schema_indexer=mock_schema_indexer,
        rules_engine=mock_rules_engine,
        tracker=mock_tracker,
    )


class TestToolExecutorRouting:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, executor):
        tc = ToolCall(id="1", name="nonexistent_tool", arguments={})
        result = await executor.execute(tc, "wf-1")
        assert "unknown tool" in result.lower()

    @pytest.mark.asyncio
    async def test_search_knowledge_no_results(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(return_value=[])
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "test"})
        result = await executor.execute(tc, "wf-1")
        assert "no relevant documents" in result.lower()

    @pytest.mark.asyncio
    async def test_search_knowledge_with_results(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "Some docs about orders",
                    "metadata": {"source_path": "docs/orders.md", "doc_type": "markdown"},
                    "distance": 0.2,
                },
            ]
        )
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "orders"})
        result = await executor.execute(tc, "wf-1")
        assert "1 relevant document" in result
        assert "orders.md" in result
        assert len(executor.ctx.rag_sources) == 1

    @pytest.mark.asyncio
    async def test_get_custom_rules_empty(self, executor, mock_rules_engine):
        mock_rules_engine.rules_to_context = MagicMock(return_value="")
        tc = ToolCall(id="1", name="get_custom_rules", arguments={})
        result = await executor.execute(tc, "wf-1")
        assert "no custom rules" in result.lower()

    @pytest.mark.asyncio
    async def test_get_custom_rules_with_rules(self, executor, mock_rules_engine):
        mock_rules_engine.rules_to_context = MagicMock(return_value="## Rules\nUse snake_case")
        tc = ToolCall(id="1", name="get_custom_rules", arguments={})
        result = await executor.execute(tc, "wf-1")
        assert "snake_case" in result

    @pytest.mark.asyncio
    async def test_execute_query_no_connection(
        self, mock_llm, mock_vector_store, mock_schema_indexer, mock_rules_engine, mock_tracker
    ):
        exec_no_conn = ToolExecutor(
            project_id="proj-1",
            connection_config=None,
            llm_router=mock_llm,
            vector_store=mock_vector_store,
            schema_indexer=mock_schema_indexer,
            rules_engine=mock_rules_engine,
            tracker=mock_tracker,
        )
        tc = ToolCall(
            id="1", name="execute_query", arguments={"query": "SELECT 1", "explanation": "test"}
        )
        result = await exec_no_conn.execute(tc, "wf-1")
        assert "no database connection" in result.lower()

    @pytest.mark.asyncio
    async def test_get_schema_info_no_connection(
        self, mock_llm, mock_vector_store, mock_schema_indexer, mock_rules_engine, mock_tracker
    ):
        exec_no_conn = ToolExecutor(
            project_id="proj-1",
            connection_config=None,
            llm_router=mock_llm,
            vector_store=mock_vector_store,
            schema_indexer=mock_schema_indexer,
            rules_engine=mock_rules_engine,
            tracker=mock_tracker,
        )
        tc = ToolCall(id="1", name="get_schema_info", arguments={"scope": "overview"})
        result = await exec_no_conn.execute(tc, "wf-1")
        assert "no database connection" in result.lower()


class TestSqlConfigForwarding:
    """ToolExecutor forwards sql_provider/sql_model to ValidationLoop."""

    @pytest.mark.asyncio
    async def test_sql_config_used_for_validation_loop(
        self, config, mock_llm, mock_vector_store,
        mock_schema_indexer, mock_rules_engine, mock_tracker,
    ):
        exec_with_sql = ToolExecutor(
            project_id="proj-1",
            connection_config=config,
            llm_router=mock_llm,
            vector_store=mock_vector_store,
            schema_indexer=mock_schema_indexer,
            rules_engine=mock_rules_engine,
            tracker=mock_tracker,
            preferred_provider="openai",
            model="gpt-4o",
            sql_provider="anthropic",
            sql_model="claude-3-opus",
        )

        assert exec_with_sql._preferred_provider == "openai"
        assert exec_with_sql._model == "gpt-4o"
        assert exec_with_sql._sql_provider == "anthropic"
        assert exec_with_sql._sql_model == "claude-3-opus"

    @pytest.mark.asyncio
    async def test_sql_config_defaults_to_agent(
        self, config, mock_llm, mock_vector_store,
        mock_schema_indexer, mock_rules_engine, mock_tracker,
    ):
        exec_no_sql = ToolExecutor(
            project_id="proj-1",
            connection_config=config,
            llm_router=mock_llm,
            vector_store=mock_vector_store,
            schema_indexer=mock_schema_indexer,
            rules_engine=mock_rules_engine,
            tracker=mock_tracker,
            preferred_provider="openai",
            model="gpt-4o",
        )

        assert exec_no_sql._sql_provider == "openai"
        assert exec_no_sql._sql_model == "gpt-4o"


class TestSchemaFormatting:
    def test_format_schema_overview(self):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(name="id", data_type="int"),
                        ColumnInfo(name="email", data_type="varchar"),
                    ],
                    row_count=100,
                ),
                TableInfo(
                    name="orders",
                    columns=[ColumnInfo(name="id", data_type="int")],
                    row_count=5000,
                ),
            ],
            db_type="postgres",
            db_name="testdb",
        )
        result = ToolExecutor._format_schema_overview(schema)
        assert "users" in result
        assert "orders" in result
        assert "2" in result  # columns count for users
        assert "~100" in result

    def test_format_table_detail_found(self):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(
                            name="id", data_type="int", is_primary_key=True, is_nullable=False
                        ),
                        ColumnInfo(name="email", data_type="varchar"),
                    ],
                    row_count=100,
                ),
            ],
            db_type="postgres",
            db_name="testdb",
        )
        result = ToolExecutor._format_table_detail(schema, "users")
        assert "## users" in result
        assert "PK" in result
        assert "email" in result

    def test_format_table_detail_not_found(self):
        schema = SchemaInfo(tables=[], db_type="postgres", db_name="testdb")
        result = ToolExecutor._format_table_detail(schema, "nonexistent")
        assert "not found" in result.lower()


class TestGetEntityInfo:
    @pytest.mark.asyncio
    async def test_get_entity_info_list(self, executor, mock_tracker):
        from app.knowledge.entity_extractor import ColumnInfo as EColumnInfo
        from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[EColumnInfo(name="id", col_type="Integer")],
        )
        executor._knowledge_cache = knowledge

        tc = ToolCall(id="1", name="get_entity_info", arguments={"scope": "list"})
        result = await executor.execute(tc, "wf-1")
        assert "User" in result
        assert "users" in result
        assert "1 entities" in result

    @pytest.mark.asyncio
    async def test_get_entity_info_detail(self, executor, mock_tracker):
        from app.knowledge.entity_extractor import ColumnInfo as EColumnInfo
        from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[
                EColumnInfo(name="id", col_type="Integer"),
                EColumnInfo(name="email", col_type="String"),
            ],
            relationships=["Post"],
        )
        executor._knowledge_cache = knowledge

        tc = ToolCall(
            id="1", name="get_entity_info", arguments={"scope": "detail", "entity_name": "User"}
        )
        result = await executor.execute(tc, "wf-1")
        assert "## User" in result
        assert "email" in result
        assert "Post" in result

    @pytest.mark.asyncio
    async def test_get_entity_info_no_knowledge(self, executor, mock_tracker):
        executor._knowledge_cache = None
        executor._load_knowledge = AsyncMock(return_value=None)

        tc = ToolCall(id="1", name="get_entity_info", arguments={"scope": "list"})
        result = await executor.execute(tc, "wf-1")
        assert "no entity information" in result.lower()

    @pytest.mark.asyncio
    async def test_get_entity_info_enums(self, executor, mock_tracker):
        from app.knowledge.entity_extractor import EnumDefinition, ProjectKnowledge

        knowledge = ProjectKnowledge()
        knowledge.enums.append(
            EnumDefinition(name="UserStatus", file_path="enums.py", values=["ACTIVE", "INACTIVE"])
        )
        executor._knowledge_cache = knowledge

        tc = ToolCall(id="1", name="get_entity_info", arguments={"scope": "enums"})
        result = await executor.execute(tc, "wf-1")
        assert "UserStatus" in result
        assert "ACTIVE" in result


class TestQueryResultFormatting:
    def test_format_empty_results(self):
        result = QueryResult(columns=["id"], rows=[], row_count=0, execution_time_ms=5.0)
        text = ToolExecutor._format_query_results(result)
        assert "no rows" in text.lower()

    def test_format_with_rows(self):
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"]],
            row_count=2,
            execution_time_ms=12.5,
        )
        text = ToolExecutor._format_query_results(result)
        assert "Alice" in text
        assert "Total rows: 2" in text
        assert "12.5ms" in text
