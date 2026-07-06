"""Unit tests for SQLAgent._union_context_tables (RET-R10 safety-net floor).

These tests are fully deterministic and do not require any live services.
"""

from app.agents.sql_agent import SQLAgent


def test_retrieved_reserved_then_safety_backfill() -> None:
    """Retrieved tables come first; only floor-passing safety-net tables fill remaining slots."""
    retrieved = ["orders", "customers", "line_items"]
    safety = [(f"t{i}", 2 + (i % 3)) for i in range(20)]  # relevance 2, 3, 4 cycling
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=15, safety_floor=3)
    # All retrieved tables must appear first, in order.
    assert out[:3] == ["orders", "customers", "line_items"]
    # Total must equal max_tables (enough above-floor safety entries exist).
    assert len(out) == 15
    # Every safety-net entry that was included must have relevance >= safety_floor.
    used_safety = set(out[3:])
    assert all(rel >= 3 for name, rel in safety if name in used_safety)


def test_safety_net_below_floor_excluded() -> None:
    """Relevance-2 entries are never included when safety_floor=3."""
    retrieved: list[str] = []
    safety = [(f"low{i}", 2) for i in range(20)]  # all relevance-2
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=15, safety_floor=3)
    assert out == []


def test_safety_net_fills_up_to_max_tables() -> None:
    """Safety net fills exactly up to max_tables when retrieved is empty."""
    retrieved: list[str] = []
    safety = [(f"t{i}", 4) for i in range(20)]
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=5, safety_floor=3)
    assert len(out) == 5
    assert all(n.startswith("t") for n in out)


def test_retrieved_not_evicted_by_large_safety_net() -> None:
    """When retrieved already fills max_tables, safety net adds nothing."""
    retrieved = ["a", "b", "c", "d", "e"]
    safety = [(f"s{i}", 5) for i in range(20)]
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=5, safety_floor=3)
    assert out == ["a", "b", "c", "d", "e"]
    assert len(out) == 5


def test_safety_net_sorted_by_relevance_desc() -> None:
    """Higher-relevance safety-net tables are preferred when budget is tight."""
    retrieved: list[str] = []
    safety = [("low", 3), ("high", 5), ("mid", 4)]
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=2, safety_floor=3)
    assert out == ["high", "mid"]


def test_dedup_between_retrieved_and_safety_net() -> None:
    """Tables in both retrieved and safety net are not duplicated."""
    retrieved = ["orders", "customers"]
    safety = [("orders", 5), ("extra", 4)]
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=5, safety_floor=3)
    assert out.count("orders") == 1
    assert "customers" in out
    assert "extra" in out


def test_exact_floor_value_included() -> None:
    """A table with relevance exactly equal to safety_floor IS included."""
    retrieved: list[str] = []
    safety = [("exact", 3), ("below", 2)]
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=5, safety_floor=3)
    assert "exact" in out
    assert "below" not in out
