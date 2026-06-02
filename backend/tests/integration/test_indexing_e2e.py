"""End-to-end test for the M1→M6 code-intelligence chain.

Drives the in-memory pipeline without spinning up a full project workflow::

    fixture repo bytes
        -> ASTParser              (M1)
        -> CodeGraphBuilder       (M2)
        -> GraphDBBridge          (M5)
        -> cluster_code_graph     (M6)
        -> CodeGraphService.save / save_clusters
        -> SchemaRetriever.build  (M4)
        -> BM25Index.build        (M3)
        -> HybridRetriever.query  (M3)

This is the only place where every milestone's output is exercised in one
test, so it doubles as a regression smoke test for the integration boundary
between the in-memory dataclasses and the persistence layer.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.ast_parser import ASTParser
from app.knowledge.bm25_index import BM25Index
from app.knowledge.code_clustering import cluster_code_graph
from app.knowledge.code_graph import CodeGraphBuilder
from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge, TableUsage
from app.knowledge.graph_db_bridge import GraphDBBridge
from app.knowledge.hybrid_retriever import HybridRetriever
from app.knowledge.schema_retriever import SchemaRetriever
from app.models.connection import Connection
from app.models.db_index import DbIndex
from app.models.project import Project
from app.models.user import User
from app.services.code_graph_service import CodeGraphService

FIXTURE = {
    "app/models/user.py": b"""
class User:
    \"\"\"User ORM model.\"\"\"

    def save(self) -> None:
        pass
""".strip(),
    "app/services/user_service.py": b"""
from app.models.user import User


def create_user(email: str) -> User:
    return User()


def list_users():
    return [User()]
""".strip(),
    "app/api/users.py": b"""
from fastapi import APIRouter

from app.services.user_service import create_user, list_users

router = APIRouter()


@router.post('/users')
def create_user_endpoint(email: str):
    return create_user(email)


@router.get('/users')
def list_users_endpoint():
    return list_users()
""".strip(),
}


@pytest_asyncio.fixture
async def project_and_conn(db_session: AsyncSession) -> tuple[str, str]:
    user = User(
        id=str(uuid.uuid4()),
        email=f"u-{uuid.uuid4().hex[:6]}@test.example",
        password_hash="x",
        display_name="Test",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="e2e",
        owner_id=user.id,
        repo_url="git@example.com:foo/bar.git",
    )
    db_session.add(project)
    await db_session.flush()
    conn = Connection(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="e2e-conn",
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
    )
    db_session.add(conn)
    await db_session.flush()
    await db_session.commit()
    return project.id, conn.id


@pytest.mark.asyncio
async def test_full_chain_m1_through_m6(db_session: AsyncSession, project_and_conn, tmp_path):
    project_id, connection_id = project_and_conn

    # ---- M1: AST parse ----------------------------------------------------
    parser = ASTParser()
    parsed_files = {}
    for path, source in FIXTURE.items():
        result = parser.parse_bytes(rel_path=path, content=source)
        assert result is not None, f"AST parse failed for {path}"
        parsed_files[path] = result

    # ---- M2: code graph ---------------------------------------------------
    builder = CodeGraphBuilder(min_call_confidence=0.3)
    code_graph = builder.build(parsed_files)
    assert code_graph.symbols, "expected symbols from fixture"

    cg_svc = CodeGraphService()
    sym_count, edge_count = await cg_svc.save(db_session, project_id, code_graph)
    assert sym_count > 0
    assert edge_count >= 1
    await db_session.commit()

    # ---- M5: graph_db_bridge ---------------------------------------------
    knowledge = ProjectKnowledge()
    knowledge.entities["User"] = EntityInfo(
        name="User",
        table_name="users",
        file_path="app/models/user.py",
    )
    knowledge.table_usage["users"] = TableUsage(table_name="users")
    bridge = GraphDBBridge(max_depth=5)
    attached = bridge.enrich(knowledge, code_graph)
    assert attached >= 1, "bridge produced no caller refs"
    assert knowledge.entities["User"].graph_callers, "graph_callers attribute should be populated"

    # ---- M6: clustering --------------------------------------------------
    clusters = cluster_code_graph(code_graph, knowledge)
    # Small fixture; clustering may not split into multiple communities.
    # We just confirm the call shape works end-to-end and persistence
    # round-trips when there *is* a cluster.
    if clusters:
        saved = await cg_svc.save_clusters(db_session, project_id, clusters)
        await db_session.commit()
        assert saved == len(clusters)
        stored = await cg_svc.get_clusters(db_session, project_id)
        assert len(stored) == len(clusters)

    # ---- M4: schema retriever -------------------------------------------
    schema_rows = [
        ("users", "application users with login email", '{"email": "login email"}'),
        ("orders", "customer orders for checkout", '{"user_id": "fk users"}'),
        (
            "products",
            "catalog of products available for purchase",
            '{"sku": "stock keeping unit"}',
        ),
        (
            "invoices",
            "billing invoices issued to customers",
            '{"total": "invoice total"}',
        ),
        (
            "payments",
            "stripe payment records and refunds",
            '{"amount": "amount paid"}',
        ),
        (
            "sessions",
            "active login session tokens",
            '{"token": "session token"}',
        ),
    ]
    for tbl, desc, notes in schema_rows:
        db_session.add(
            DbIndex(
                id=str(uuid.uuid4()),
                connection_id=connection_id,
                table_name=tbl,
                business_description=desc,
                column_notes_json=notes,
                is_active=True,
                relevance_score=3,
            )
        )
    await db_session.commit()

    from app.services.db_index_service import DbIndexService

    db_idx_svc = DbIndexService()
    entries = await db_idx_svc.get_index(db_session, connection_id)
    schema_retriever = SchemaRetriever(data_dir=tmp_path / "bm25")
    schema_retriever.build(connection_id, indexed_sha="sha-e2e", entries=entries)
    hits = schema_retriever.query(connection_id, "find users by email", k=3)
    assert hits
    assert hits[0]["metadata"]["table_name"] in {"users", "orders"}

    # ---- M3: BM25 + hybrid retrieval ------------------------------------
    bm25 = BM25Index(tmp_path / "bm25_docs")
    docs = [
        (
            "doc-user",
            "User model with email and password authentication",
            {"source_path": "app/models/user.py"},
        ),
        (
            "doc-create",
            "create_user service function creating new users",
            {"source_path": "app/services/user_service.py"},
        ),
        (
            "doc-orders",
            "order service handling checkout flow",
            {"source_path": "app/services/order_service.py"},
        ),
        (
            "doc-billing",
            "billing module for invoices and refunds",
            {"source_path": "app/services/billing.py"},
        ),
        (
            "doc-config",
            "application configuration loader",
            {"source_path": "app/config.py"},
        ),
    ]
    bm25.build(project_id, indexed_sha="sha-e2e", documents=docs)

    class _StubVectorStore:
        def query(self, *args, **kwargs):
            return []

    retriever = HybridRetriever(bm25=bm25, vector_store=_StubVectorStore())
    results = await retriever.query(
        project_id=project_id,
        query_text="how does user creation work",
        k=5,
    )
    assert results
    assert any(r.doc_id == "doc-create" for r in results)


# ----------------------------------------------------------------------------
# Consumer-facing surfaces: prompts, agents, and lifecycle hooks.
# ----------------------------------------------------------------------------
#
# These cover the "M1-M6 signals must actually reach the LLM" half of the
# integration. They are intentionally close to the audit findings so each
# assertion maps to one previously-broken wire.


def test_sql_prompt_surfaces_lineage_cluster_and_schema_retrieval():
    """The SQL system prompt must teach the model about new tools / sections.

    Without this, M4 (`get_query_context` ranks tables question-aware), M5
    ('Lineage (top callers)' inside `get_query_context`), and M6
    (`get_tables_in_cluster`) are invisible to the LLM even though the
    indexing pipeline has populated them.
    """
    from app.agents.prompts.sql_prompt import build_sql_system_prompt

    prompt = build_sql_system_prompt(
        db_type="postgres",
        has_db_index=True,
        has_code_db_sync=True,
        has_code_clusters=True,
        lineage_enabled=True,
        schema_retrieval_enabled=True,
    )

    assert "question-aware" in prompt
    assert "Lineage" in prompt
    assert "get_tables_in_cluster" in prompt

    minimal = build_sql_system_prompt(db_type="postgres")
    assert "get_tables_in_cluster" not in minimal
    assert "question-aware" not in minimal


def test_knowledge_prompt_surfaces_hybrid_and_lineage():
    from app.agents.prompts.knowledge_prompt import build_knowledge_system_prompt

    prompt = build_knowledge_system_prompt(
        hybrid_retrieval_enabled=True,
        lineage_enabled=True,
    )
    assert "Reciprocal Rank Fusion" in prompt or "hybrid retrieval" in prompt.lower()
    assert "Code lineage" in prompt or "lineage" in prompt.lower()

    minimal = build_knowledge_system_prompt()
    assert "Reciprocal Rank Fusion" not in minimal


def test_knowledge_agent_renders_graph_callers(monkeypatch):
    """`_format_entity_detail` must surface M5 lineage when the flag is on."""
    from app.agents.knowledge_agent import KnowledgeAgent
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "lineage_enabled", True)

    knowledge = ProjectKnowledge()
    entity = EntityInfo(
        name="User",
        table_name="users",
        file_path="app/models/user.py",
    )
    entity.graph_callers = [
        {
            "caller_name": "create_user_endpoint",
            "caller_file": "app/api/users.py",
            "endpoint_kind": "http_route",
            "op_kind": "write",
            "confidence": 0.85,
        }
    ]
    knowledge.entities["User"] = entity

    out = KnowledgeAgent._format_entity_detail(knowledge, "User")
    assert "Code lineage" in out
    assert "create_user_endpoint" in out
    assert "app/api/users.py" in out
    assert "http_route" in out

    # Same call with the flag off must hide the section (legacy view).
    monkeypatch.setattr(app_settings, "lineage_enabled", False)
    legacy = KnowledgeAgent._format_entity_detail(knowledge, "User")
    assert "Code lineage" not in legacy


@pytest.mark.asyncio
async def test_code_graph_service_load_graph_roundtrip(db_session: AsyncSession, project_and_conn):
    """``load_graph`` must rehydrate a previously-saved graph for resume paths.

    When the pipeline resumes after a partial failure, ``state.code_graph``
    is empty in memory. Without this rehydrate, M5 / M6 silently skip even
    though Postgres still has the data from the earlier successful run.
    """
    project_id, _ = project_and_conn

    parser = ASTParser()
    parsed_files = {
        path: parser.parse_bytes(rel_path=path, content=source) for path, source in FIXTURE.items()
    }
    code_graph = CodeGraphBuilder(min_call_confidence=0.3).build(parsed_files)
    cg_svc = CodeGraphService()
    sym_count, edge_count = await cg_svc.save(db_session, project_id, code_graph)
    await db_session.commit()
    assert sym_count > 0

    rehydrated = await cg_svc.load_graph(db_session, project_id)
    assert rehydrated is not None
    assert len(rehydrated.symbols) == sym_count
    assert len(rehydrated.edges) == edge_count

    # Unknown project must return None, not crash.
    missing = await cg_svc.load_graph(db_session, str(uuid.uuid4()))
    assert missing is None


def test_indexing_artifacts_cleanup_is_idempotent(tmp_path, monkeypatch):
    """Cleanup must be best-effort: idempotent + never raises.

    Project / connection delete paths invoke this; a raise here would
    leave Postgres rows half-deleted, which is much worse than a leaked
    .pkl. Re-running cleanup on the same id must be a no-op.
    """
    from app.config import settings as app_settings
    from app.knowledge.bm25_index import BM25Index
    from app.knowledge.schema_retriever import SchemaRetriever
    from app.services.indexing_artifacts import (
        cleanup_connection_artifacts,
        cleanup_project_artifacts,
    )

    monkeypatch.setattr(app_settings, "bm25_data_dir", str(tmp_path))

    project_id = f"proj-{uuid.uuid4().hex[:8]}"
    bm25 = BM25Index(tmp_path)
    bm25.build(
        project_id,
        indexed_sha="sha-cleanup",
        documents=[("d1", "hello", {})],
    )
    pkls_before = list(tmp_path.glob("*.pkl"))
    assert pkls_before, "build should have written a .pkl"

    cleanup_project_artifacts(project_id)
    # Idempotent — the second call must not raise even though file is gone.
    cleanup_project_artifacts(project_id)

    # The contract is "the on-disk snapshot is gone". In-memory caches in
    # other BM25Index instances are a separate concern (each instance owns
    # its own cache).
    pkls_after = list(tmp_path.glob("*.pkl"))
    assert not pkls_after, f"expected no .pkl after cleanup, got {pkls_after}"

    # Schema retriever path mirrors the same contract. Use a real DbIndex
    # row (not persisted — just constructed) so attribute access matches
    # production exactly.
    conn_id = f"conn-{uuid.uuid4().hex[:8]}"
    retriever = SchemaRetriever(data_dir=tmp_path)
    entry = DbIndex(
        id=str(uuid.uuid4()),
        connection_id=conn_id,
        table_name="users",
        business_description="user accounts",
        column_notes_json='{"email": "login email"}',
        is_active=True,
        relevance_score=1,
    )
    retriever.build(conn_id, indexed_sha="sha-cleanup", entries=[entry])
    cleanup_connection_artifacts(conn_id)
    cleanup_connection_artifacts(conn_id)  # idempotent
    # No exception → contract held.


def test_metrics_snapshot_counters_prefix_filter():
    """JSON ``/api/metrics`` filters via ``snapshot_counters(prefix=...)``."""
    from app.core.metrics import get_metrics_collector

    m = get_metrics_collector()
    m.inc("code_graph_symbols_total", 5, project="abc")
    m.inc("code_graph_edges_total", 3, project="abc")
    m.inc("orchestrator_requests_total", 1, route="unified")

    cg = m.snapshot_counters(prefix="code_graph_")
    assert cg.get("code_graph_symbols_total", 0) >= 5
    assert cg.get("code_graph_edges_total", 0) >= 3
    assert "orchestrator_requests_total" not in cg

    everything = m.snapshot_counters()
    assert "orchestrator_requests_total" in everything
