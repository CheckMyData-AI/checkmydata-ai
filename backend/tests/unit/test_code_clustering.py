"""Unit tests for the M6 clustering module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_clustering import (
    _parse_label_response,
    cluster_code_graph,
    label_clusters,
)
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_IMPORTS,
    CodeGraph,
    GraphEdge,
)
from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge


def _sym(uid: str, name: str, file_path: str, *, kind: str = "function") -> Symbol:
    return Symbol(
        uid=uid,
        kind=kind,
        name=name,
        file_path=file_path,
        start_line=1,
        end_line=2,
        language="python",
    )


@pytest.fixture
def two_cluster_graph():
    """Two tightly-connected sub-components representing 'auth' and 'billing'."""
    auth_syms = [
        _sym(f"auth_{i}", f"auth_fn_{i}", "app/auth/handlers.py")
        for i in range(5)
    ]
    billing_syms = [
        _sym(f"bill_{i}", f"bill_fn_{i}", "app/billing/stripe.py")
        for i in range(5)
    ]
    edges = []
    # Dense intra-cluster CALLS edges.
    for syms in (auth_syms, billing_syms):
        for i, s in enumerate(syms):
            for j, t in enumerate(syms):
                if i == j:
                    continue
                edges.append(
                    GraphEdge(
                        src_uid=s.uid,
                        dst_uid=t.uid,
                        edge_type=EDGE_CALLS,
                        confidence=0.9,
                    )
                )
    # A single weak link between the two so Louvain has a chance to split.
    edges.append(
        GraphEdge(
            src_uid=auth_syms[0].uid,
            dst_uid=billing_syms[0].uid,
            edge_type=EDGE_IMPORTS,
            confidence=0.4,
        )
    )
    return CodeGraph(auth_syms + billing_syms, edges)


def _knowledge_with_tables() -> ProjectKnowledge:
    k = ProjectKnowledge()
    k.entities["AuthUser"] = EntityInfo(
        name="auth_fn_0",
        table_name="users",
        file_path="app/auth/handlers.py",
    )
    k.entities["Invoice"] = EntityInfo(
        name="bill_fn_0",
        table_name="invoices",
        file_path="app/billing/stripe.py",
    )
    return k


def test_cluster_code_graph_returns_communities(two_cluster_graph):
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    # We expect two distinct clusters of size 5 each.
    assert len(clusters) == 2
    assert all(c.symbol_count == 5 for c in clusters)


def test_cluster_assigns_member_uids_and_files(two_cluster_graph):
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    for c in clusters:
        assert all(uid in two_cluster_graph.symbols for uid in c.member_uids)
        assert c.file_paths  # at least one file


def test_cluster_aggregates_table_names(two_cluster_graph):
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    all_tables = set()
    for c in clusters:
        all_tables.update(c.table_names)
    assert "users" in all_tables
    assert "invoices" in all_tables


def test_cluster_min_size_filter():
    """Clusters with fewer than _MIN_CLUSTER_SIZE symbols are dropped."""
    sym = _sym("u1", "lonely", "f.py")
    graph = CodeGraph([sym], [])
    clusters = cluster_code_graph(graph, ProjectKnowledge())
    assert clusters == []


def test_cluster_empty_graph():
    graph = CodeGraph([], [])
    assert cluster_code_graph(graph, ProjectKnowledge()) == []


def test_cluster_louvain_deterministic_via_seed(two_cluster_graph):
    """``louvain_communities(..., seed=42)`` returns the same result twice."""
    knowledge = _knowledge_with_tables()
    a = cluster_code_graph(two_cluster_graph, knowledge)
    b = cluster_code_graph(two_cluster_graph, knowledge)
    a_keys = sorted(tuple(sorted(c.member_uids)) for c in a)
    b_keys = sorted(tuple(sorted(c.member_uids)) for c in b)
    assert a_keys == b_keys


def test_parse_label_response_handles_clean_json():
    text = (
        '{"id": "0", "label": "Auth & Sessions", "description": "User login"}\n'
        '{"id": "1", "label": "Stripe Billing", "description": "Payments"}'
    )
    out = _parse_label_response(text)
    assert out["0"] == ("Auth & Sessions", "User login")
    assert out["1"] == ("Stripe Billing", "Payments")


def test_parse_label_response_skips_garbage():
    text = (
        "Sure! Here you go:\n"
        '{"id": "0", "label": "Auth"}\n'
        "not json\n"
        '{"id": "1", "label": "Billing", "description": "ok"}\n'
    )
    out = _parse_label_response(text)
    assert set(out.keys()) == {"0", "1"}


@pytest.mark.asyncio
async def test_label_clusters_uses_default_when_router_missing(two_cluster_graph):
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    assert clusters
    await label_clusters(clusters, two_cluster_graph, llm_router=None)
    assert all(c.label.startswith("Cluster ") for c in clusters)


@pytest.mark.asyncio
async def test_label_clusters_calls_llm_and_applies_labels(two_cluster_graph):
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    # Order from cluster_code_graph is descending by size; for our fixture
    # both are 5 symbols, so we sort by id to make assertions deterministic.
    clusters = sorted(clusters, key=lambda c: c.cluster_id)
    fake_response = MagicMock(content=(
        '{"id": "0", "label": "Auth & Sessions", "description": "Login"}\n'
        '{"id": "1", "label": "Stripe Billing", "description": "Money"}\n'
    ))

    fake_router = MagicMock()
    fake_router.complete = AsyncMock(return_value=fake_response)

    await label_clusters(clusters, two_cluster_graph, llm_router=fake_router, batch_size=10)
    labels = {c.cluster_id: c.label for c in clusters}
    assert labels.get("0") == "Auth & Sessions"
    assert labels.get("1") == "Stripe Billing"


@pytest.mark.asyncio
async def test_label_clusters_swallows_llm_failure(two_cluster_graph):
    """If the LLM raises, we keep the default 'Cluster N' label."""
    knowledge = _knowledge_with_tables()
    clusters = cluster_code_graph(two_cluster_graph, knowledge)
    fake_router = MagicMock()
    fake_router.complete = AsyncMock(side_effect=RuntimeError("boom"))
    await label_clusters(clusters, two_cluster_graph, llm_router=fake_router)
    assert all(c.label.startswith("Cluster ") for c in clusters)
