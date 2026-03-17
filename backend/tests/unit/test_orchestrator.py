from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig, QueryResult, SchemaInfo
from app.core.orchestrator import Orchestrator, OrchestratorResponse
from app.llm.base import LLMResponse, ToolCall


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.complete = AsyncMock()
    router.stream = AsyncMock()
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    return vs


@pytest.fixture
def mock_custom_rules():
    cr = MagicMock()
    cr.load_rules = MagicMock(return_value=[])
    cr.load_db_rules = AsyncMock(return_value=[])
    cr.rules_to_context = MagicMock(return_value="")
    return cr


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
def orchestrator(mock_llm_router, mock_vector_store, mock_custom_rules):
    return Orchestrator(
        llm_router=mock_llm_router,
        vector_store=mock_vector_store,
        custom_rules=mock_custom_rules,
    )


class TestOrchestratorConnectorKey:
    def test_key_includes_db_info(self, orchestrator, config):
        key = orchestrator._connector_key(config)
        assert "postgres" in key
        assert "localhost" in key
        assert "5432" in key
        assert "testdb" in key

    def test_key_includes_ssh_info(self, orchestrator):
        config = ConnectionConfig(
            db_type="postgres",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="deploy",
        )
        key = orchestrator._connector_key(config)
        assert "jump.example.com" in key
        assert "22" in key
        assert "deploy" in key

    def test_different_ssh_different_keys(self, orchestrator):
        config_a = ConnectionConfig(
            db_type="postgres",
            db_host="db",
            db_port=5432,
            db_name="mydb",
            ssh_host="jump1.example.com",
            ssh_port=22,
            ssh_user="a",
        )
        config_b = ConnectionConfig(
            db_type="postgres",
            db_host="db",
            db_port=5432,
            db_name="mydb",
            ssh_host="jump2.example.com",
            ssh_port=22,
            ssh_user="b",
        )
        assert orchestrator._connector_key(config_a) != orchestrator._connector_key(config_b)


class TestOrchestratorProcessQuestion:
    @pytest.mark.asyncio
    async def test_successful_query(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="execute_query",
                            arguments={"query": "SELECT 1", "explanation": "test"},
                        )
                    ],
                ),
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="recommend_visualization",
                            arguments={
                                "viz_type": "table",
                                "config": "{}",
                                "summary": "Result is 1",
                            },
                        )
                    ],
                ),
            ]
        )

        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(
                columns=["?column?"],
                rows=[[1]],
                row_count=1,
                execution_time_ms=1.0,
            )
        )
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="What is 1?",
                project_id="test-project",
                connection_config=config,
            )

        assert isinstance(result, OrchestratorResponse)
        assert result.query == "SELECT 1"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_safety_blocks_dangerous_query(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="execute_query",
                        arguments={"query": "DROP TABLE users", "explanation": "drop"},
                    )
                ],
            )
        )

        mock_connector = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="Drop users table",
                project_id="test-project",
                connection_config=config,
            )

        assert result.error is not None
        assert "blocked" in result.answer.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_query_generated(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="I cannot generate a query for this.",
            )
        )

        mock_connector = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="Hello",
                project_id="test-project",
                connection_config=config,
            )

        assert result.error is not None


class TestOrchestratorDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_all(self, orchestrator):
        mock_conn = AsyncMock()
        orchestrator._connectors["key1"] = mock_conn
        orchestrator._schema_cache["key1"] = (SchemaInfo(db_type="postgres"), 0.0)
        await orchestrator.disconnect_all()
        mock_conn.disconnect.assert_called_once()
        assert len(orchestrator._connectors) == 0
        assert len(orchestrator._schema_cache) == 0
