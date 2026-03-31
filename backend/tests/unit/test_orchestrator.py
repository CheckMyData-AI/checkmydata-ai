from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.connectors.base import ConnectionConfig, QueryResult, SchemaInfo
from app.core.orchestrator import Orchestrator, OrchestratorResponse
from app.llm.base import LLMResponse, Message, ToolCall


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


class TestEnricherReceivesSyncAndRules:
    """Orchestrator passes sync/rules/distinct_values to ContextEnricher."""

    @pytest.mark.asyncio
    async def test_enricher_receives_sync_and_rules(self, orchestrator, mock_llm_router, config):
        from unittest.mock import patch as _patch

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

        captured_enricher_kwargs = {}

        original_init = None

        def capture_enricher_init(self_enricher, *args, **kwargs):
            captured_enricher_kwargs.update(kwargs)
            original_init(self_enricher, *args, **kwargs)

        from app.core.context_enricher import ContextEnricher

        original_init = ContextEnricher.__init__

        mock_sync_entry = MagicMock()
        mock_sync_entry.table_name = "orders"
        mock_sync_entry.conversion_warnings = "amount in cents"

        mock_db_entry = MagicMock()
        mock_db_entry.table_name = "orders"
        mock_db_entry.column_distinct_values_json = '{"status": ["active"]}'

        with (
            _patch("app.core.orchestrator.get_connector", return_value=mock_connector),
            _patch.object(
                orchestrator,
                "_get_sync_for_repair",
                new_callable=AsyncMock,
                return_value=("- orders: amount in cents", ""),
            ),
            _patch.object(
                orchestrator,
                "_get_repair_rules_context",
                new_callable=AsyncMock,
                return_value="Use amount/100",
            ),
            _patch.object(
                orchestrator,
                "_get_distinct_values",
                new_callable=AsyncMock,
                return_value={"orders": {"status": ["active"]}},
            ),
            _patch.object(ContextEnricher, "__init__", side_effect=capture_enricher_init),
        ):
            _result = await orchestrator.process_question(
                question="What is 1?",
                project_id="test-project",
                connection_config=config,
            )

        assert "sync_context" in captured_enricher_kwargs
        assert captured_enricher_kwargs["sync_context"] == "- orders: amount in cents"
        assert "rules_context" in captured_enricher_kwargs
        assert captured_enricher_kwargs["rules_context"] == "Use amount/100"
        assert "distinct_values" in captured_enricher_kwargs
        assert "orders" in captured_enricher_kwargs["distinct_values"]


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


# -------------------------------------------------------------------
# OrchestratorAgent tool-call dedup & history boundary tests
# -------------------------------------------------------------------


class TestDedupToolCalls:
    """Tests for OrchestratorAgent._dedup_tool_calls static method."""

    def _tc(self, id: str, name: str = "query_database", question: str = "") -> ToolCall:
        args = {"question": question} if question else {}
        return ToolCall(id=id, name=name, arguments=args)

    def test_no_duplicates_passes_through(self):
        calls = [
            self._tc("1", question="revenue last month"),
            self._tc("2", question="user count"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_exact_duplicate_removed(self):
        calls = [
            self._tc("1", question="revenue last month"),
            self._tc("2", question="revenue last month"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 1
        assert kept[0].id == "1"
        assert "2" in skipped
        assert "Duplicate" in skipped["2"]

    def test_non_query_database_not_deduped(self):
        calls = [
            self._tc("1", name="process_data", question="some op"),
            self._tc("2", name="process_data", question="some op"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_history_matched_question_skipped(self):
        history = [
            Message(role="user", content="show revenue last month"),
            Message(role="assistant", content="here is the revenue last month data"),
        ]
        calls = [
            self._tc("1", question="revenue last month"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, history)
        assert len(kept) == 0
        assert "1" in skipped
        assert "already retrieved" in skipped["1"]

    def test_short_question_not_history_matched(self):
        history = [
            Message(role="assistant", content="here is data for total users"),
        ]
        calls = [
            self._tc("1", question="total"),  # too short (<=15 chars)
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, history)
        assert len(kept) == 1
        assert len(skipped) == 0

    def test_mixed_kept_and_skipped(self):
        calls = [
            self._tc("1", question="revenue by country"),
            self._tc("2", question="revenue by country"),  # duplicate
            self._tc("3", question="active users today"),
            self._tc("4", name="search_codebase", question="what is X"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 3
        assert "2" in skipped

    def test_empty_calls(self):
        kept, skipped = OrchestratorAgent._dedup_tool_calls([], [])
        assert kept == []
        assert skipped == {}


class TestHistoryBoundaryInPrompt:
    """Verify the orchestrator prompt builder includes focus directives."""

    def test_current_turn_focus_in_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "CURRENT TURN FOCUS" in prompt
        assert "TOOL CALL ECONOMY" in prompt
        assert "SINGLE-QUESTION RULE" in prompt

    def test_guidelines_still_present(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "GUIDELINES:" in prompt
        assert "query_database" in prompt
        assert "REQUEST ANALYSIS PROTOCOL" in prompt

    def test_single_question_rule_excludes_process_data(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "data retrieval" in prompt
        assert "process_data" in prompt
        assert "do not count toward this limit" in prompt


class TestLegacyQueryBuilderBoundary:
    """Verify the legacy QueryBuilder injects a history boundary."""

    @pytest.mark.asyncio
    async def test_boundary_injected_when_history_present(self):
        from app.core.query_builder import QueryBuilder

        mock_router = MagicMock()
        mock_resp = MagicMock()
        mock_resp.tool_calls = [
            MagicMock(
                name="execute_query",
                arguments={"query": "SELECT 1", "explanation": "test"},
            )
        ]
        mock_resp.usage = {}
        mock_router.complete = AsyncMock(return_value=mock_resp)

        from app.llm.base import Message

        history = [
            Message(role="user", content="old question"),
            Message(role="assistant", content="old answer"),
            Message(role="user", content="another old question"),
            Message(role="assistant", content="another old answer"),
            Message(role="user", content="yet another"),
            Message(role="assistant", content="yet another answer"),
        ]

        qb = QueryBuilder(mock_router)
        await qb.build_query("new question", "schema", "", "postgres", chat_history=history)

        call_messages = mock_router.complete.call_args.kwargs.get(
            "messages",
            mock_router.complete.call_args[0][0] if mock_router.complete.call_args[0] else [],
        )
        texts = [m.content for m in call_messages]
        assert any("END OF CONVERSATION HISTORY" in t for t in texts)
        assert (
            len([m for m in call_messages if m.role == "user" and m.content == "old question"]) == 0
        )

    @pytest.mark.asyncio
    async def test_no_boundary_when_no_history(self):
        from app.core.query_builder import QueryBuilder

        mock_router = MagicMock()
        mock_resp = MagicMock()
        mock_resp.tool_calls = [
            MagicMock(
                name="execute_query",
                arguments={"query": "SELECT 1", "explanation": "test"},
            )
        ]
        mock_resp.usage = {}
        mock_router.complete = AsyncMock(return_value=mock_resp)

        qb = QueryBuilder(mock_router)
        await qb.build_query("new question", "schema", "", "postgres")

        call_messages = mock_router.complete.call_args.kwargs.get(
            "messages",
            mock_router.complete.call_args[0][0] if mock_router.complete.call_args[0] else [],
        )
        texts = [m.content for m in call_messages]
        assert not any("END OF CONVERSATION HISTORY" in t for t in texts)
