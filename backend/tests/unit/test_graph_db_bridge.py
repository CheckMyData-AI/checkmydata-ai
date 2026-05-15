"""Unit tests for :class:`GraphDBBridge` (M5).

We build a synthetic :class:`CodeGraph` rather than driving the AST parser
so the tests are fast, deterministic, and don't depend on tree-sitter
grammars. The bridge only cares about the graph contract
(``callers_of`` / ``symbols`` / ``query_by_name``) and the symbol fields it
inspects (``name``, ``file_path``, ``decorators``).
"""

from __future__ import annotations

import pytest

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import EDGE_CALLS, CodeGraph, GraphEdge
from app.knowledge.entity_extractor import (
    EntityInfo,
    ProjectKnowledge,
    TableUsage,
)
from app.knowledge.graph_db_bridge import (
    CallerRef,
    GraphDBBridge,
    classify_endpoint_kind,
    classify_op_kind,
)


def _sym(
    uid: str,
    name: str,
    file_path: str,
    *,
    kind: str = "function",
    decorators: tuple[str, ...] = (),
    signature: str = "",
) -> Symbol:
    return Symbol(
        uid=uid,
        kind=kind,
        name=name,
        file_path=file_path,
        start_line=1,
        end_line=2,
        language="python",
        decorators=decorators,
        signature=signature,
    )


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


class TestClassifyEndpointKind:
    def test_http_by_path(self):
        s = _sym("u1", "list_users", "app/api/users.py")
        assert classify_endpoint_kind(s) == "http"

    def test_http_by_decorator(self):
        s = _sym("u1", "list_users", "lib/whatever.py", decorators=("router.get",))
        assert classify_endpoint_kind(s) == "http"

    def test_migration_path_wins_over_service(self):
        s = _sym("u1", "upgrade", "src/alembic/versions/0001_add_table.py")
        assert classify_endpoint_kind(s) == "migration"

    def test_service_layer(self):
        s = _sym("u1", "process_order", "app/services/order_service.py")
        assert classify_endpoint_kind(s) == "service"

    def test_cli_path(self):
        s = _sym("u1", "import_data", "app/cli/import.py")
        assert classify_endpoint_kind(s) == "cli"

    def test_unknown_default(self):
        s = _sym("u1", "helper", "app/utils/misc.py")
        assert classify_endpoint_kind(s) == "unknown"

    def test_windows_path_separators(self):
        s = _sym("u1", "view", "app\\api\\foo.py")
        assert classify_endpoint_kind(s) == "http"


class TestClassifyOpKind:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("create_user", "write"),
            ("update_profile", "write"),
            ("delete_order", "write"),
            ("save_invoice", "write"),
            ("set_status", "write"),
            ("get_user", "read"),
            ("find_by_id", "read"),
            ("list_orders", "read"),
            ("count_subscriptions", "read"),
            ("noop", "unknown"),
        ],
    )
    def test_verbs(self, name, expected):
        assert classify_op_kind(_sym("u", name, "f.py")) == expected

    def test_http_post_decorator_means_write(self):
        s = _sym("u", "handle", "f.py", decorators=("router.post('/x')",))
        assert classify_op_kind(s) == "write"

    def test_http_get_decorator_means_read(self):
        s = _sym("u", "handle", "f.py", decorators=("@router.get('/x')",))
        assert classify_op_kind(s) == "read"


# ---------------------------------------------------------------------------
# Bridge end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def call_chain_graph():
    """A 3-hop call chain: http_endpoint -> service_fn -> model_method (User)."""
    symbols = [
        _sym(
            "python:app/models/user.py:class:User:1",
            "User",
            "app/models/user.py",
            kind="class",
        ),
        _sym(
            "python:app/services/user_service.py:function:create_user:1",
            "create_user",
            "app/services/user_service.py",
        ),
        _sym(
            "python:app/api/users.py:function:create:1",
            "create",
            "app/api/users.py",
            decorators=("router.post('/users')",),
        ),
    ]
    edges = [
        GraphEdge(
            src_uid="python:app/services/user_service.py:function:create_user:1",
            dst_uid="python:app/models/user.py:class:User:1",
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
        GraphEdge(
            src_uid="python:app/api/users.py:function:create:1",
            dst_uid="python:app/services/user_service.py:function:create_user:1",
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
    ]
    return CodeGraph(symbols, edges)


def _knowledge_with_user_entity(file_path: str = "app/models/user.py") -> ProjectKnowledge:
    knowledge = ProjectKnowledge()
    knowledge.entities["User"] = EntityInfo(
        name="User",
        table_name="users",
        file_path=file_path,
    )
    knowledge.table_usage["users"] = TableUsage(table_name="users")
    return knowledge


def test_enrich_attaches_callers_to_entity(call_chain_graph):
    knowledge = _knowledge_with_user_entity()
    bridge = GraphDBBridge(max_depth=5)
    attached = bridge.enrich(knowledge, call_chain_graph)
    assert attached == 2  # service_fn + http_endpoint

    refs = knowledge.entities["User"].graph_callers
    names = [r["caller_name"] for r in refs]
    assert "create_user" in names
    assert "create" in names

    # HTTP endpoint classification flows through.
    http_ref = next(r for r in refs if r["caller_name"] == "create")
    assert http_ref["endpoint_kind"] == "http"
    assert http_ref["op_kind"] == "write"


def test_enrich_sorts_by_confidence_desc(call_chain_graph):
    knowledge = _knowledge_with_user_entity()
    GraphDBBridge(max_depth=5).enrich(knowledge, call_chain_graph)
    refs = knowledge.entities["User"].graph_callers
    confs = [float(r["confidence"]) for r in refs]
    assert confs == sorted(confs, reverse=True)


def test_enrich_is_idempotent(call_chain_graph):
    knowledge = _knowledge_with_user_entity()
    bridge = GraphDBBridge(max_depth=5)
    bridge.enrich(knowledge, call_chain_graph)
    count_first = len(knowledge.entities["User"].graph_callers)
    bridge.enrich(knowledge, call_chain_graph)
    count_second = len(knowledge.entities["User"].graph_callers)
    assert count_first == count_second


def test_enrich_respects_max_callers(call_chain_graph):
    knowledge = _knowledge_with_user_entity()
    bridge = GraphDBBridge(max_depth=5, max_callers_per_entity=1)
    bridge.enrich(knowledge, call_chain_graph)
    assert len(knowledge.entities["User"].graph_callers) == 1


def test_enrich_respects_max_depth():
    """``max_depth=1`` keeps only the direct caller."""
    symbols = [
        _sym(
            "python:app/models/user.py:class:User:1",
            "User",
            "app/models/user.py",
            kind="class",
        ),
        _sym(
            "python:app/services/svc.py:function:level1:1",
            "level1",
            "app/services/svc.py",
        ),
        _sym(
            "python:app/api/route.py:function:level2:1",
            "level2",
            "app/api/route.py",
        ),
    ]
    edges = [
        GraphEdge(
            src_uid="python:app/services/svc.py:function:level1:1",
            dst_uid="python:app/models/user.py:class:User:1",
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
        GraphEdge(
            src_uid="python:app/api/route.py:function:level2:1",
            dst_uid="python:app/services/svc.py:function:level1:1",
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
    ]
    graph = CodeGraph(symbols, edges)
    knowledge = _knowledge_with_user_entity()
    GraphDBBridge(max_depth=1).enrich(knowledge, graph)
    names = [r["caller_name"] for r in knowledge.entities["User"].graph_callers]
    assert names == ["level1"]


def test_enrich_handles_entity_without_matching_symbol():
    """If the entity name doesn't exist in the graph we still get an empty list."""
    knowledge = _knowledge_with_user_entity()
    graph = CodeGraph(symbols=[], edges=[])
    attached = GraphDBBridge().enrich(knowledge, graph)
    assert attached == 0
    assert knowledge.entities["User"].graph_callers == []


def test_enrich_falls_back_to_name_only_match():
    """When file_path doesn't line up, name-only lookup still finds the symbol."""
    knowledge = _knowledge_with_user_entity(file_path="app/somewhere_else.py")
    symbols = [
        _sym(
            "python:app/models/user.py:class:User:1",
            "User",
            "app/models/user.py",
            kind="class",
        ),
        _sym(
            "python:app/api/x.py:function:list_users:1",
            "list_users",
            "app/api/x.py",
            decorators=("router.get",),
        ),
    ]
    edges = [
        GraphEdge(
            src_uid="python:app/api/x.py:function:list_users:1",
            dst_uid="python:app/models/user.py:class:User:1",
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
    ]
    graph = CodeGraph(symbols, edges)
    GraphDBBridge().enrich(knowledge, graph)
    names = [r["caller_name"] for r in knowledge.entities["User"].graph_callers]
    assert "list_users" in names


def test_enrich_dedupes_caller_across_multiple_entity_anchors():
    """If two symbols match an entity, the same caller is recorded once."""
    knowledge = _knowledge_with_user_entity()
    # Two ``User`` symbols (e.g. orm + dataclass).
    user_sym = _sym(
        "python:app/models/user.py:class:User:1",
        "User",
        "app/models/user.py",
        kind="class",
    )
    user_sym2 = _sym(
        "python:app/dataclasses/user.py:class:User:1",
        "User",
        "app/dataclasses/user.py",
        kind="class",
    )
    caller = _sym(
        "python:app/api/users.py:function:list:1",
        "list",
        "app/api/users.py",
        decorators=("router.get('/users')",),
    )
    edges = [
        GraphEdge(
            src_uid=caller.uid,
            dst_uid=user_sym.uid,
            edge_type=EDGE_CALLS,
            confidence=0.9,
        ),
        GraphEdge(
            src_uid=caller.uid,
            dst_uid=user_sym2.uid,
            edge_type=EDGE_CALLS,
            confidence=0.8,
        ),
    ]
    graph = CodeGraph([user_sym, user_sym2, caller], edges)
    GraphDBBridge().enrich(knowledge, graph)
    refs = knowledge.entities["User"].graph_callers
    # Same caller, single entry, highest-confidence kept.
    assert len(refs) == 1
    assert refs[0]["caller_name"] == "list"
    assert float(refs[0]["confidence"]) >= 0.85


def test_caller_ref_serializes_to_plain_dict():
    """``to_dict`` must produce JSON-safe values (no tuples / no nested dataclasses)."""
    import json

    ref = CallerRef(
        caller_name="x",
        caller_file="f.py",
        caller_kind="function",
        endpoint_kind="http",
        op_kind="write",
        depth=1,
        confidence=0.42,
        decorators=("router.post",),
    )
    payload = ref.to_dict()
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    assert parsed["decorators"] == ["router.post"]
    assert parsed["confidence"] == 0.42
