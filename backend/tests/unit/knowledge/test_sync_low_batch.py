"""TDD tests for Wave-5 low-batch fixes: L11, L12, L13.

L14 is in tests/unit/services/test_knowledge_freshness_service.py (appended separately).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# L11 — _coerce_confidence: round float, clamp 1-5, only truly non-numeric → 3
# ---------------------------------------------------------------------------


def test_l11_float_string_rounds_not_defaults():
    """'4.5' should round to 4 (nearest int), NOT return the old default of 3."""
    from app.knowledge.code_db_sync_analyzer import _coerce_confidence

    assert _coerce_confidence("4.5") == 4


def test_l11_float_high_rounds_up():
    """4.7 (float) should round to 5."""
    from app.knowledge.code_db_sync_analyzer import _coerce_confidence

    assert _coerce_confidence(4.7) == 5


def test_l11_non_numeric_still_returns_3():
    """A garbage string should still return the safe default 3."""
    from app.knowledge.code_db_sync_analyzer import _coerce_confidence

    assert _coerce_confidence("x") == 3


def test_l11_out_of_range_int_clamped():
    """9 should clamp to 5 (upper bound)."""
    from app.knowledge.code_db_sync_analyzer import _coerce_confidence

    assert _coerce_confidence(9) == 5


def test_l11_float_that_rounds_to_one():
    """1.2 → round → 1 (lower bound, still in 1..5)."""
    from app.knowledge.code_db_sync_analyzer import _coerce_confidence

    assert _coerce_confidence(1.2) == 1


# ---------------------------------------------------------------------------
# L12 — CallerRef.depth_estimated: to_dict includes depth_estimated=True
#        _build_code_context render does NOT emit a "depth=" literal for
#        estimated refs
# ---------------------------------------------------------------------------


def test_l12_caller_ref_to_dict_has_depth_estimated():
    """CallerRef.to_dict() must include depth_estimated: bool."""
    from app.knowledge.graph_db_bridge import CallerRef

    ref = CallerRef(
        caller_name="create_order",
        caller_file="app/routes/orders.py",
        caller_kind="function",
        endpoint_kind="http",
        op_kind="write",
        depth=-1,
        confidence=0.6,
    )
    d = ref.to_dict()
    assert "depth_estimated" in d
    assert d["depth_estimated"] is True  # fabricated depth → always True


def test_l12_build_code_context_no_depth_literal_for_estimated(tmp_path):
    """When depth is estimated the rendered context must not contain 'depth='."""
    from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
    from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

    entity = EntityInfo(
        name="Order",
        file_path="app/models/order.py",
        columns=[],
        relationships=[],
        graph_callers=[
            {
                "endpoint_kind": "http",
                "caller_name": "create_order",
                "caller_file": "app/routes/orders.py",
                "caller_kind": "function",
                "op_kind": "write",
                "depth": -1,
                "depth_estimated": True,
                "confidence": 0.6,
            }
        ],
    )

    result = CodeDbSyncPipeline._build_code_context(
        entity=entity,
        usage=None,
        knowledge=ProjectKnowledge(),
        table_lower="order",
    )
    # The old dead line was `int(r.get("depth", 1))` which didn't output anything;
    # the new contract is that a depth= token is never written for estimated refs.
    assert "depth=" not in result


# ---------------------------------------------------------------------------
# L13 — enum-table link uses word-boundary, not raw substring
# ---------------------------------------------------------------------------


def test_l13_substring_mismatch_not_linked():
    """Enum 'reorder_reason' must NOT be linked to table 'order' via substring."""
    from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
    from app.knowledge.entity_extractor import EnumDefinition, ProjectKnowledge

    knowledge = ProjectKnowledge(
        enums=[EnumDefinition(name="reorder_reason", values=["low_stock"], file_path="")]
    )
    result = CodeDbSyncPipeline._build_code_context(
        entity=None,
        usage=None,
        knowledge=knowledge,
        table_lower="order",
    )
    assert "reorder_reason" not in result


def test_l13_exact_word_match_is_linked():
    """Enum 'order_status' MUST be linked to table 'order' (word boundary match)."""
    from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
    from app.knowledge.entity_extractor import EnumDefinition, ProjectKnowledge

    knowledge = ProjectKnowledge(
        enums=[EnumDefinition(name="order_status", values=["pending", "shipped"], file_path="")]
    )
    result = CodeDbSyncPipeline._build_code_context(
        entity=None,
        usage=None,
        knowledge=knowledge,
        table_lower="order",
    )
    assert "order_status" in result
