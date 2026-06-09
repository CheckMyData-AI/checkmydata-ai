"""Unit tests for Phase 5 cross-source primitives.

Covers the schema-change diff/detector, the multi-DB JOIN planner, and the
cross-source causal graph. All pure logic — no DB or network required.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.cross_source import (
    CrossSourceCausalGraph,
    CrossSourceJoinPlanner,
)
from app.services.schema_change_detector import diff_fingerprints

# --------------------------------------------------------------------------- #
# Schema-change diff
# --------------------------------------------------------------------------- #


def test_diff_detects_added_removed_changed() -> None:
    prev = {"public.orders": "a", "public.users": "b", "public.legacy": "c"}
    cur = {"public.orders": "a", "public.users": "B!", "public.new": "d"}
    diff = diff_fingerprints(prev, cur)

    assert diff.added == ["public.new"]
    assert diff.removed == ["public.legacy"]
    assert diff.changed == ["public.users"]
    assert diff.has_changes
    assert diff.affected == ["public.new", "public.users"]


def test_diff_no_changes_is_positive_and_empty() -> None:
    fp = {"t1": "x", "t2": "y"}
    diff = diff_fingerprints(fp, dict(fp))
    assert not diff.has_changes
    assert diff.severity() == "positive"
    assert diff.summary() == "no changes"


def test_diff_removal_is_warning_severity() -> None:
    diff = diff_fingerprints({"t1": "x", "t2": "y"}, {"t1": "x"})
    assert diff.removed == ["t2"]
    assert diff.severity() == "warning"


def test_diff_change_only_is_info_severity() -> None:
    diff = diff_fingerprints({"t1": "x"}, {"t1": "z"})
    assert diff.changed == ["t1"]
    assert diff.severity() == "info"


# --------------------------------------------------------------------------- #
# Multi-DB JOIN planner
# --------------------------------------------------------------------------- #


def _orders_schema() -> dict[str, list[dict]]:
    return {
        "conn_a": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary_key": True},
                    {"name": "customer_id", "data_type": "int"},
                    {"name": "total", "data_type": "numeric"},
                ],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_table": "customers",
                        "references_column": "id",
                    }
                ],
            },
        ],
        "conn_b": [
            {
                "name": "customers",
                "columns": [
                    {"name": "customer_id", "data_type": "bigint", "is_primary_key": True},
                    {"name": "email", "data_type": "varchar(255)"},
                ],
                "foreign_keys": [],
            },
        ],
    }


def test_join_planner_matches_cross_connection_key() -> None:
    planner = CrossSourceJoinPlanner()
    candidates = planner.plan(_orders_schema())

    assert candidates, "expected at least one cross-connection join candidate"
    top = candidates[0]
    cols = {top.left.column.lower(), top.right.column.lower()}
    assert cols == {"customer_id"}
    conns = {top.left.connection_id, top.right.connection_id}
    assert conns == {"conn_a", "conn_b"}
    # pk↔fk + id-suffix should push confidence comfortably above baseline.
    assert top.confidence >= 0.8
    assert "pk↔fk" in top.reason


def test_join_planner_skips_same_connection_and_type_mismatch() -> None:
    schemas = {
        "conn_a": [
            {
                "name": "t1",
                "columns": [{"name": "ref_id", "data_type": "int"}],
                "foreign_keys": [],
            },
            {
                "name": "t2",
                "columns": [{"name": "ref_id", "data_type": "int"}],
                "foreign_keys": [],
            },
        ],
        "conn_b": [
            {
                "name": "t3",
                "columns": [{"name": "ref_id", "data_type": "text"}],
                "foreign_keys": [],
            },
        ],
    }
    candidates = CrossSourceJoinPlanner().plan(schemas)
    # Same-conn pair (t1,t2) excluded; cross-conn pair has type mismatch.
    assert candidates == []


def test_join_planner_generic_name_is_low_confidence() -> None:
    schemas = {
        "conn_a": [
            {"name": "a", "columns": [{"name": "name", "data_type": "text"}], "foreign_keys": []},
        ],
        "conn_b": [
            {"name": "b", "columns": [{"name": "name", "data_type": "text"}], "foreign_keys": []},
        ],
    }
    # Default min_confidence (0.4) filters out the weak generic match (0.3).
    assert CrossSourceJoinPlanner().plan(schemas) == []
    loose = CrossSourceJoinPlanner().plan(schemas, min_confidence=0.0)
    assert loose and loose[0].confidence < 0.4


# --------------------------------------------------------------------------- #
# Cross-source causal graph
# --------------------------------------------------------------------------- #


@dataclass
class _SyncRow:
    entity_name: str
    table_name: str
    read_count: int = 0
    write_count: int = 0


def test_graph_fk_edges_flow_parent_to_child() -> None:
    g = CrossSourceCausalGraph()
    g.add_fk_edges(
        "c1",
        [
            {
                "name": "orders",
                "foreign_keys": [{"column": "customer_id", "references_table": "customers"}],
            }
        ],
    )
    parent = CrossSourceCausalGraph.db_node("c1", "customers")
    child = CrossSourceCausalGraph.db_node("c1", "orders")
    # customers feeds orders → orders is downstream of customers.
    assert child in g.downstream(parent)
    assert parent in g.upstream(child)
    assert g.edge_count() == 1


def test_graph_lineage_write_and_read_directions() -> None:
    g = CrossSourceCausalGraph()
    g.add_lineage_edges(
        "c1",
        [
            _SyncRow("OrderWriter", "orders", write_count=5),
            _SyncRow("OrderReport", "orders", read_count=3),
        ],
    )
    tbl = CrossSourceCausalGraph.db_node("c1", "orders")
    writer = CrossSourceCausalGraph.code_node("OrderWriter")
    reader = CrossSourceCausalGraph.code_node("OrderReport")

    # Writer feeds the table; the table feeds the reader.
    assert tbl in g.downstream(writer)
    assert reader in g.downstream(tbl)


def test_graph_transitive_upstream_across_code_and_db() -> None:
    g = CrossSourceCausalGraph()
    g.add_fk_edges(
        "c1",
        [{"name": "orders", "foreign_keys": [{"column": "cid", "references_table": "customers"}]}],
    )
    g.add_lineage_edges("c1", [_SyncRow("OrderSvc", "orders", write_count=1)])

    customers = CrossSourceCausalGraph.db_node("c1", "customers")
    svc = CrossSourceCausalGraph.code_node("OrderSvc")
    # OrderSvc -> orders -> (orders feeds nothing downstream of customers)
    # customers -> orders (FK), OrderSvc -> orders (write); orders downstream
    # of both. Transitive downstream of OrderSvc includes orders only.
    assert CrossSourceCausalGraph.db_node("c1", "orders") in g.downstream(svc)
    assert g.node_count() >= 3
    assert customers in g.upstream(CrossSourceCausalGraph.db_node("c1", "orders"))
