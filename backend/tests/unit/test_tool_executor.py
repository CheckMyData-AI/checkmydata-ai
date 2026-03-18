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
        connection_id="conn-1",
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
        self,
        config,
        mock_llm,
        mock_vector_store,
        mock_schema_indexer,
        mock_rules_engine,
        mock_tracker,
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
        self,
        config,
        mock_llm,
        mock_vector_store,
        mock_schema_indexer,
        mock_rules_engine,
        mock_tracker,
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


class TestSearchKnowledgeRAGThreshold:
    """RAG relevance threshold filters low-quality results."""

    @pytest.mark.asyncio
    async def test_search_knowledge_filters_low_relevance(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "Irrelevant content about logging",
                    "metadata": {"source_path": "logs.md", "doc_type": "markdown"},
                    "distance": 0.8,
                },
            ]
        )
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "orders"})
        result = await executor.execute(tc, "wf-1")
        assert "no sufficiently relevant" in result.lower()
        assert len(executor.ctx.rag_sources) == 0

    @pytest.mark.asyncio
    async def test_search_knowledge_keeps_high_relevance(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "Orders table documentation",
                    "metadata": {"source_path": "docs/orders.md", "doc_type": "markdown"},
                    "distance": 0.5,
                },
            ]
        )
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "orders"})
        result = await executor.execute(tc, "wf-1")
        assert "orders.md" in result
        assert len(executor.ctx.rag_sources) == 1

    @pytest.mark.asyncio
    async def test_search_knowledge_threshold_boundary(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "Included at boundary",
                    "metadata": {"source_path": "a.md", "doc_type": "markdown"},
                    "distance": 0.7,
                },
                {
                    "document": "Excluded just above",
                    "metadata": {"source_path": "b.md", "doc_type": "markdown"},
                    "distance": 0.71,
                },
            ]
        )
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "test"})
        result = await executor.execute(tc, "wf-1")
        assert "a.md" in result
        assert "b.md" not in result
        assert len(executor.ctx.rag_sources) == 1

    @pytest.mark.asyncio
    async def test_search_knowledge_no_distance_included(self, executor, mock_vector_store):
        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "No distance info doc",
                    "metadata": {"source_path": "c.md", "doc_type": "markdown"},
                },
            ]
        )
        tc = ToolCall(id="1", name="search_knowledge", arguments={"query": "test"})
        result = await executor.execute(tc, "wf-1")
        assert "c.md" in result
        assert len(executor.ctx.rag_sources) == 1


class TestGetDbIndex:
    """Tests for the get_db_index tool handler."""

    @pytest.mark.asyncio
    async def test_get_db_index_no_connection(
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
        tc = ToolCall(id="1", name="get_db_index", arguments={"scope": "overview"})
        result = await exec_no_conn.execute(tc, "wf-1")
        assert "no database connection" in result.lower()

    @pytest.mark.asyncio
    async def test_get_db_index_overview(self, executor, mock_tracker):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "orders"
        mock_entry.is_active = True
        mock_entry.relevance_score = 5
        mock_entry.business_description = "Contains order data"
        mock_entry.row_count = 1000

        mock_svc = MagicMock()
        mock_svc.get_index = AsyncMock(return_value=[mock_entry])
        mock_svc.get_summary = AsyncMock(return_value=None)
        mock_svc.index_to_prompt_context = MagicMock(return_value="## DB Index\norders - active")

        with _patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            with _patch(
                "app.services.db_index_service.DbIndexService",
                return_value=mock_svc,
            ):
                tc = ToolCall(id="1", name="get_db_index", arguments={"scope": "overview"})
                result = await executor.execute(tc, "wf-1")

        assert "orders" in result

    @pytest.mark.asyncio
    async def test_get_db_index_table_detail(self, executor, mock_tracker):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "users"

        mock_svc = MagicMock()
        mock_svc.get_table_index = AsyncMock(return_value=mock_entry)
        mock_svc.table_index_to_detail = MagicMock(
            return_value="## users\nid: int PK\nemail: varchar"
        )

        with _patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            with _patch(
                "app.services.db_index_service.DbIndexService",
                return_value=mock_svc,
            ):
                tc = ToolCall(
                    id="1",
                    name="get_db_index",
                    arguments={"scope": "table_detail", "table_name": "users"},
                )
                result = await executor.execute(tc, "wf-1")

        assert "users" in result
        assert "email" in result


class TestGetSyncContext:
    """Tests for the get_sync_context tool handler."""

    @pytest.mark.asyncio
    async def test_get_sync_context_no_connection(
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
        tc = ToolCall(id="1", name="get_sync_context", arguments={"scope": "overview"})
        result = await exec_no_conn.execute(tc, "wf-1")
        assert "no database connection" in result.lower()

    @pytest.mark.asyncio
    async def test_get_sync_context_overview(self, executor, mock_tracker):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "orders"
        mock_entry.sync_status = "matched"

        mock_svc = MagicMock()
        mock_svc.get_sync = AsyncMock(return_value=[mock_entry])
        mock_svc.get_summary = AsyncMock(return_value=None)
        mock_svc.sync_to_prompt_context = MagicMock(return_value="## Sync\norders - synced")

        with _patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            with _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_svc,
            ):
                tc = ToolCall(id="1", name="get_sync_context", arguments={"scope": "overview"})
                result = await executor.execute(tc, "wf-1")

        assert "orders" in result

    @pytest.mark.asyncio
    async def test_get_sync_context_table_detail(self, executor, mock_tracker):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "orders"
        mock_entry.conversion_warnings = "amount stored in cents"

        mock_svc = MagicMock()
        mock_svc.get_table_sync = AsyncMock(return_value=mock_entry)
        mock_svc.table_sync_to_detail = MagicMock(return_value="## orders\namount in cents")

        with _patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            with _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_svc,
            ):
                tc = ToolCall(
                    id="1",
                    name="get_sync_context",
                    arguments={"scope": "table_detail", "table_name": "orders"},
                )
                result = await executor.execute(tc, "wf-1")

        assert "orders" in result
        assert "cents" in result


class TestGetQueryContext:
    """Tests for the unified get_query_context tool."""

    @pytest.mark.asyncio
    async def test_no_connection(
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
            id="1",
            name="get_query_context",
            arguments={"question": "how many orders?"},
        )
        result = await exec_no_conn.execute(tc, "wf-1")
        assert "no database connection" in result.lower()

    @pytest.mark.asyncio
    async def test_no_db_index(self, executor, mock_tracker):
        from unittest.mock import patch as _patch

        mock_db_svc = MagicMock()
        mock_db_svc.get_index = AsyncMock(return_value=[])
        mock_sync_svc = MagicMock()
        mock_sync_svc.get_sync = AsyncMock(return_value=[])
        mock_sync_svc.get_summary = AsyncMock(return_value=None)
        mock_learn_svc = MagicMock()
        mock_learn_svc.get_learnings = AsyncMock(return_value=[])

        with _patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            with (
                _patch("app.services.db_index_service.DbIndexService", return_value=mock_db_svc),
                _patch(
                    "app.services.code_db_sync_service.CodeDbSyncService",
                    return_value=mock_sync_svc,
                ),
                _patch(
                    "app.services.agent_learning_service.AgentLearningService",
                    return_value=mock_learn_svc,
                ),
            ):
                tc = ToolCall(
                    id="1",
                    name="get_query_context",
                    arguments={"question": "how many orders?"},
                )
                result = await executor.execute(tc, "wf-1")

        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_basic_context(self, executor, mock_tracker, mock_rules_engine, config):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "orders"
        mock_entry.is_active = True
        mock_entry.relevance_score = 5
        mock_entry.business_description = "Order records"
        mock_entry.row_count = 500
        mock_entry.column_notes_json = "{}"
        mock_entry.column_distinct_values_json = '{"status": ["active", "cancelled"]}'
        mock_entry.query_hints = ""

        mock_db_svc = MagicMock()
        mock_db_svc.get_index = AsyncMock(return_value=[mock_entry])

        mock_sync_svc = MagicMock()
        mock_sync_svc.get_sync = AsyncMock(return_value=[])
        mock_sync_svc.get_summary = AsyncMock(return_value=None)

        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="orders",
                    columns=[
                        ColumnInfo(name="id", data_type="int", is_primary_key=True),
                        ColumnInfo(name="status", data_type="varchar"),
                        ColumnInfo(name="amount", data_type="decimal"),
                    ],
                    row_count=500,
                ),
            ],
            db_type="postgres",
            db_name="testdb",
        )

        mock_learn_svc = MagicMock()
        mock_learn_svc.get_learnings = AsyncMock(return_value=[])

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch("app.services.db_index_service.DbIndexService", return_value=mock_db_svc),
            _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_sync_svc,
            ),
            _patch(
                "app.services.agent_learning_service.AgentLearningService",
                return_value=mock_learn_svc,
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            executor._get_cached_schema = AsyncMock(return_value=schema)
            executor._load_knowledge = AsyncMock(return_value=None)

            tc = ToolCall(
                id="1",
                name="get_query_context",
                arguments={"question": "show orders", "table_names": "orders"},
            )
            result = await executor.execute(tc, "wf-1")

        assert "orders" in result.lower()
        assert "status" in result.lower()
        assert "active" in result

    @pytest.mark.asyncio
    async def test_with_sync_data(self, executor, mock_tracker, mock_rules_engine, config):
        from unittest.mock import patch as _patch

        mock_entry = MagicMock()
        mock_entry.table_name = "orders"
        mock_entry.is_active = True
        mock_entry.relevance_score = 5
        mock_entry.business_description = "Orders"
        mock_entry.row_count = 100
        mock_entry.column_notes_json = "{}"
        mock_entry.column_distinct_values_json = "{}"
        mock_entry.query_hints = ""

        mock_sync_entry = MagicMock()
        mock_sync_entry.table_name = "orders"
        mock_sync_entry.conversion_warnings = "amount stored in cents, divide by 100"
        mock_sync_entry.column_sync_notes_json = '{"amount": "Value in cents"}'
        mock_sync_entry.query_recommendations = "Use amount/100 for dollars"

        mock_db_svc = MagicMock()
        mock_db_svc.get_index = AsyncMock(return_value=[mock_entry])

        mock_sync_svc = MagicMock()
        mock_sync_svc.get_sync = AsyncMock(return_value=[mock_sync_entry])
        mock_sync_svc.get_summary = AsyncMock(return_value=None)

        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="orders",
                    columns=[
                        ColumnInfo(name="id", data_type="int"),
                        ColumnInfo(name="amount", data_type="int"),
                    ],
                ),
            ],
            db_type="postgres",
        )

        mock_learn_svc = MagicMock()
        mock_learn_svc.get_learnings = AsyncMock(return_value=[])

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch("app.services.db_index_service.DbIndexService", return_value=mock_db_svc),
            _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_sync_svc,
            ),
            _patch(
                "app.services.agent_learning_service.AgentLearningService",
                return_value=mock_learn_svc,
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            executor._get_cached_schema = AsyncMock(return_value=schema)
            executor._load_knowledge = AsyncMock(return_value=None)

            tc = ToolCall(
                id="1",
                name="get_query_context",
                arguments={"question": "total orders", "table_names": "orders"},
            )
            result = await executor.execute(tc, "wf-1")

        assert "cents" in result.lower()
        assert "WARNINGS" in result

    @pytest.mark.asyncio
    async def test_with_custom_rules(self, executor, mock_tracker, mock_rules_engine, config):
        from unittest.mock import patch as _patch

        mock_rules_engine.load_rules = MagicMock(
            return_value=[MagicMock(content="Always use snake_case for column names", tags=[])]
        )

        mock_entry = MagicMock()
        mock_entry.table_name = "users"
        mock_entry.is_active = True
        mock_entry.relevance_score = 5
        mock_entry.business_description = "Users"
        mock_entry.row_count = 10
        mock_entry.column_notes_json = "{}"
        mock_entry.column_distinct_values_json = "{}"
        mock_entry.query_hints = ""

        mock_db_svc = MagicMock()
        mock_db_svc.get_index = AsyncMock(return_value=[mock_entry])

        mock_sync_svc = MagicMock()
        mock_sync_svc.get_sync = AsyncMock(return_value=[])
        mock_sync_svc.get_summary = AsyncMock(return_value=None)

        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    columns=[ColumnInfo(name="id", data_type="int")],
                ),
            ],
            db_type="postgres",
        )

        mock_learn_svc = MagicMock()
        mock_learn_svc.get_learnings = AsyncMock(return_value=[])

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch("app.services.db_index_service.DbIndexService", return_value=mock_db_svc),
            _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_sync_svc,
            ),
            _patch(
                "app.services.agent_learning_service.AgentLearningService",
                return_value=mock_learn_svc,
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            executor._get_cached_schema = AsyncMock(return_value=schema)
            executor._load_knowledge = AsyncMock(return_value=None)

            tc = ToolCall(
                id="1",
                name="get_query_context",
                arguments={"question": "show users", "table_names": "users"},
            )
            result = await executor.execute(tc, "wf-1")

        assert "Query Context" in result

    @pytest.mark.asyncio
    async def test_auto_detect_tables(self, executor):
        entry_orders = MagicMock()
        entry_orders.table_name = "orders"
        entry_orders.is_active = True
        entry_orders.relevance_score = 5
        entry_orders.business_description = "Customer orders"

        entry_logs = MagicMock()
        entry_logs.table_name = "logs"
        entry_logs.is_active = True
        entry_logs.relevance_score = 2
        entry_logs.business_description = "Application logs"

        result = executor._auto_detect_tables("show all orders", [entry_orders, entry_logs])
        table_names = [e.table_name for e in result]
        assert "orders" in table_names

    @pytest.mark.asyncio
    async def test_table_names_filter(self, executor, mock_tracker, mock_rules_engine, config):
        from unittest.mock import patch as _patch

        entry_orders = MagicMock()
        entry_orders.table_name = "orders"
        entry_orders.is_active = True
        entry_orders.relevance_score = 5
        entry_orders.business_description = "Orders"
        entry_orders.row_count = 100
        entry_orders.column_notes_json = "{}"
        entry_orders.column_distinct_values_json = "{}"
        entry_orders.query_hints = ""

        entry_users = MagicMock()
        entry_users.table_name = "users"
        entry_users.is_active = True
        entry_users.relevance_score = 5
        entry_users.business_description = "Users"
        entry_users.row_count = 50
        entry_users.column_notes_json = "{}"
        entry_users.column_distinct_values_json = "{}"
        entry_users.query_hints = ""

        mock_db_svc = MagicMock()
        mock_db_svc.get_index = AsyncMock(return_value=[entry_orders, entry_users])

        mock_sync_svc = MagicMock()
        mock_sync_svc.get_sync = AsyncMock(return_value=[])
        mock_sync_svc.get_summary = AsyncMock(return_value=None)

        schema = SchemaInfo(
            tables=[
                TableInfo(name="orders", columns=[ColumnInfo(name="id", data_type="int")]),
                TableInfo(name="users", columns=[ColumnInfo(name="id", data_type="int")]),
            ],
            db_type="postgres",
        )

        mock_learn_svc = MagicMock()
        mock_learn_svc.get_learnings = AsyncMock(return_value=[])

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch("app.services.db_index_service.DbIndexService", return_value=mock_db_svc),
            _patch(
                "app.services.code_db_sync_service.CodeDbSyncService",
                return_value=mock_sync_svc,
            ),
            _patch(
                "app.services.agent_learning_service.AgentLearningService",
                return_value=mock_learn_svc,
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_sf.return_value = mock_session

            executor._get_cached_schema = AsyncMock(return_value=schema)
            executor._load_knowledge = AsyncMock(return_value=None)

            tc = ToolCall(
                id="1",
                name="get_query_context",
                arguments={"question": "count", "table_names": "orders"},
            )
            result = await executor.execute(tc, "wf-1")

        assert "orders" in result.lower()


class TestFormatTableContext:
    """Tests for _format_table_context with fixed read_queries/write_queries."""

    def test_code_usage_as_counts(self):
        from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

        db_entry = MagicMock()
        db_entry.table_name = "users"
        db_entry.business_description = "User accounts"
        db_entry.row_count = 100
        db_entry.column_notes_json = "{}"
        db_entry.column_distinct_values_json = "{}"
        db_entry.query_hints = ""

        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[],
            read_queries=5,
            write_queries=3,
        )

        result = ToolExecutor._format_table_context(db_entry, None, None, knowledge)
        assert "Code usage: 5 reads, 3 writes" in result

    def test_no_crash_on_zero_queries(self):
        from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

        db_entry = MagicMock()
        db_entry.table_name = "users"
        db_entry.business_description = ""
        db_entry.row_count = None
        db_entry.column_notes_json = "{}"
        db_entry.column_distinct_values_json = "{}"
        db_entry.query_hints = ""

        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[],
            read_queries=0,
            write_queries=0,
        )

        result = ToolExecutor._format_table_context(db_entry, None, None, knowledge)
        assert "Code usage" not in result


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


class TestGetAvailableToolsIncludesManageRules:
    def test_manage_custom_rules_present_with_connection(self):
        from app.core.tools import get_available_tools

        tools = get_available_tools(has_connection=True)
        names = [t.name for t in tools]
        assert "manage_custom_rules" in names

    def test_manage_custom_rules_absent_without_connection(self):
        from app.core.tools import get_available_tools

        tools = get_available_tools(has_connection=False, has_knowledge_base=True)
        names = [t.name for t in tools]
        assert "manage_custom_rules" not in names


class TestManageCustomRules:
    """Tests for the manage_custom_rules tool handler."""

    @pytest.fixture
    def executor_with_user(
        self,
        config,
        mock_llm,
        mock_vector_store,
        mock_schema_indexer,
        mock_rules_engine,
        mock_tracker,
    ):
        return ToolExecutor(
            project_id="proj-1",
            connection_config=config,
            llm_router=mock_llm,
            vector_store=mock_vector_store,
            schema_indexer=mock_schema_indexer,
            rules_engine=mock_rules_engine,
            tracker=mock_tracker,
            user_id="user-owner",
        )

    def _mock_session_and_patches(self):
        from unittest.mock import patch as _patch

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return _patch, mock_session

    @pytest.mark.asyncio
    async def test_create_rule(self, executor_with_user):
        _patch, mock_session = self._mock_session_and_patches()

        mock_membership = MagicMock()
        mock_membership.get_role = AsyncMock(return_value="owner")
        mock_rule = MagicMock()
        mock_rule.id = "rule-1"
        mock_rule.name = "Amount in cents"
        mock_rule.content = "Divide orders.amount by 100"
        mock_rule_svc = MagicMock()
        mock_rule_svc.create = AsyncMock(return_value=mock_rule)

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch(
                "app.services.membership_service.MembershipService",
                return_value=mock_membership,
            ),
            _patch("app.services.rule_service.RuleService", return_value=mock_rule_svc),
        ):
            mock_sf.return_value = mock_session
            tc = ToolCall(
                id="1",
                name="manage_custom_rules",
                arguments={
                    "action": "create",
                    "name": "Amount in cents",
                    "content": "Divide orders.amount by 100",
                },
            )
            result = await executor_with_user.execute(tc, "wf-1")

        assert "created successfully" in result.lower()
        assert "Amount in cents" in result
        assert "rule-1" in result
        mock_rule_svc.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_rule(self, executor_with_user):
        _patch, mock_session = self._mock_session_and_patches()

        mock_membership = MagicMock()
        mock_membership.get_role = AsyncMock(return_value="owner")
        mock_rule = MagicMock()
        mock_rule.id = "rule-1"
        mock_rule.name = "Updated name"
        mock_rule.content = "Updated content"
        mock_rule_svc = MagicMock()
        mock_rule_svc.update = AsyncMock(return_value=mock_rule)

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch(
                "app.services.membership_service.MembershipService",
                return_value=mock_membership,
            ),
            _patch("app.services.rule_service.RuleService", return_value=mock_rule_svc),
        ):
            mock_sf.return_value = mock_session
            tc = ToolCall(
                id="1",
                name="manage_custom_rules",
                arguments={
                    "action": "update",
                    "rule_id": "rule-1",
                    "content": "Updated content",
                },
            )
            result = await executor_with_user.execute(tc, "wf-1")

        assert "updated successfully" in result.lower()
        mock_rule_svc.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_rule(self, executor_with_user):
        _patch, mock_session = self._mock_session_and_patches()

        mock_membership = MagicMock()
        mock_membership.get_role = AsyncMock(return_value="owner")
        mock_rule_svc = MagicMock()
        mock_rule_svc.delete = AsyncMock(return_value=True)

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch(
                "app.services.membership_service.MembershipService",
                return_value=mock_membership,
            ),
            _patch("app.services.rule_service.RuleService", return_value=mock_rule_svc),
        ):
            mock_sf.return_value = mock_session
            tc = ToolCall(
                id="1",
                name="manage_custom_rules",
                arguments={"action": "delete", "rule_id": "rule-1"},
            )
            result = await executor_with_user.execute(tc, "wf-1")

        assert "deleted successfully" in result.lower()
        mock_rule_svc.delete.assert_awaited_once_with(mock_session, "rule-1")

    @pytest.mark.asyncio
    async def test_create_missing_name(self, executor_with_user):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={"action": "create", "content": "some content"},
        )
        result = await executor_with_user.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "name" in result.lower()

    @pytest.mark.asyncio
    async def test_create_missing_content(self, executor_with_user):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={"action": "create", "name": "My rule"},
        )
        result = await executor_with_user.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "content" in result.lower()

    @pytest.mark.asyncio
    async def test_update_missing_rule_id(self, executor_with_user):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={"action": "update", "content": "new content"},
        )
        result = await executor_with_user.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "rule_id" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_missing_rule_id(self, executor_with_user):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={"action": "delete"},
        )
        result = await executor_with_user.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "rule_id" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_action(self, executor_with_user):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={"action": "list"},
        )
        result = await executor_with_user.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "invalid action" in result.lower()

    @pytest.mark.asyncio
    async def test_permission_denied_for_non_owner(self, executor_with_user):
        _patch, mock_session = self._mock_session_and_patches()

        mock_membership = MagicMock()
        mock_membership.get_role = AsyncMock(return_value="viewer")

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch(
                "app.services.membership_service.MembershipService",
                return_value=mock_membership,
            ),
            _patch("app.services.rule_service.RuleService"),
        ):
            mock_sf.return_value = mock_session
            tc = ToolCall(
                id="1",
                name="manage_custom_rules",
                arguments={
                    "action": "create",
                    "name": "Test",
                    "content": "Test content",
                },
            )
            result = await executor_with_user.execute(tc, "wf-1")

        assert "permission denied" in result.lower()

    @pytest.mark.asyncio
    async def test_no_user_id(self, executor):
        tc = ToolCall(
            id="1",
            name="manage_custom_rules",
            arguments={
                "action": "create",
                "name": "Test",
                "content": "Test content",
            },
        )
        result = await executor.execute(tc, "wf-1")
        assert "error" in result.lower()
        assert "user identity" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, executor_with_user):
        _patch, mock_session = self._mock_session_and_patches()

        mock_membership = MagicMock()
        mock_membership.get_role = AsyncMock(return_value="owner")
        mock_rule_svc = MagicMock()
        mock_rule_svc.delete = AsyncMock(return_value=False)

        with (
            _patch("app.models.base.async_session_factory") as mock_sf,
            _patch(
                "app.services.membership_service.MembershipService",
                return_value=mock_membership,
            ),
            _patch("app.services.rule_service.RuleService", return_value=mock_rule_svc),
        ):
            mock_sf.return_value = mock_session
            tc = ToolCall(
                id="1",
                name="manage_custom_rules",
                arguments={"action": "delete", "rule_id": "nonexistent"},
            )
            result = await executor_with_user.execute(tc, "wf-1")

        assert "not found" in result.lower()
