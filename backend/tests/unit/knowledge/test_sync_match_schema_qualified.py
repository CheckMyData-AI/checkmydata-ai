# backend/tests/unit/knowledge/test_sync_match_schema_qualified.py
"""Tests for schema-qualified code↔DB matching in _match_tables (SYNC-L6).

Verifies that when a code entity carries a schema-qualified table_name
(e.g. "analytics.orders"), it matches only the DB table with the same
(schema, bare_name) pair — NOT a same-bare-name table in a different
schema ("public.orders").

Also verifies backward compat: unqualified code entities still match
by bare name.
"""

import json

from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    ProjectKnowledge,
)


# ---------------------------------------------------------------------------
# Minimal DB entry stub (mirrors DbIndex interface used by _match_tables)
# ---------------------------------------------------------------------------
class _DbEntry:
    def __init__(self, name: str, schema: str = "public"):
        self.table_name = name
        self.table_schema = schema
        self.business_description = ""
        self.row_count = None
        self.column_count = 0
        self.data_patterns = ""
        self.query_hints = ""
        self.column_notes_json = "{}"
        self.column_distinct_values_json = json.dumps({})
        self.sample_data_json = json.dumps([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pipeline() -> CodeDbSyncPipeline:
    """Construct a pipeline with all optional services stubbed out."""
    import unittest.mock as mock

    p = CodeDbSyncPipeline.__new__(CodeDbSyncPipeline)
    p._db_index_svc = mock.MagicMock()
    p._llm_router = mock.MagicMock()
    p._rules_engine = mock.MagicMock()
    p._rules_engine.load_rules.return_value = []
    p._rules_engine.load_db_rules = mock.AsyncMock(return_value=[])
    p._rules_engine.rules_to_context.return_value = ""
    return p


def _knowledge_with_entity(table_name: str, entity_name: str = "Order") -> ProjectKnowledge:
    """Build a minimal ProjectKnowledge with one entity."""
    entity = EntityInfo(
        name=entity_name,
        table_name=table_name,
        columns=[ColumnInfo(name="id", col_type="int")],
    )
    pk = ProjectKnowledge()
    pk.entities[entity_name] = entity
    return pk


# ---------------------------------------------------------------------------
# T1: qualified entity → must NOT cross-contaminate same-bare-name table
# ---------------------------------------------------------------------------


def test_qualified_entity_matches_correct_schema_only():
    """public.orders and analytics.orders are both in DB.

    A code entity with table_name="analytics.orders" must attach its code
    context ONLY to the analytics.orders matched row, not to public.orders.
    """
    db_public = _DbEntry("orders", "public")
    db_analytics = _DbEntry("orders", "analytics")

    knowledge = _knowledge_with_entity("analytics.orders", "AnalyticsOrder")
    pipeline = _pipeline()

    results = pipeline._match_tables(knowledge, [db_public, db_analytics])

    # Both DB tables must appear in results
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    by_display = {r.table_name: r for r in results}

    # Determine which key corresponds to which schema by inspecting code_context
    analytics_row = by_display.get("analytics.orders")
    public_row = by_display.get("public.orders")

    assert analytics_row is not None, (
        f"Expected 'analytics.orders' in results; got keys: {list(by_display)}"
    )
    assert public_row is not None, (
        f"Expected 'public.orders' in results; got keys: {list(by_display)}"
    )

    # analytics.orders should carry entity code context (entity name visible)
    assert "AnalyticsOrder" in analytics_row.code_context or "analytics.orders" in (
        analytics_row.code_context
    ), f"analytics.orders row should have entity code context; got: {analytics_row.code_context!r}"

    # public.orders must NOT carry the AnalyticsOrder entity code context
    assert "AnalyticsOrder" not in public_row.code_context, (
        "Cross-schema contamination: AnalyticsOrder entity leaked into public.orders row. "
        f"public_row.code_context={public_row.code_context!r}"
    )


# ---------------------------------------------------------------------------
# T2: unqualified entity → still matches by bare name (back-compat)
# ---------------------------------------------------------------------------


def test_unqualified_entity_matches_by_bare_name():
    """Only public.orders in DB; code entity has bare table_name="orders".

    Must still match (backward compatibility preserved).
    """
    db_public = _DbEntry("orders", "public")
    knowledge = _knowledge_with_entity("orders", "Order")
    pipeline = _pipeline()

    results = pipeline._match_tables(knowledge, [db_public])

    assert len(results) == 1
    row = results[0]
    # Entity code context must be present
    assert "Order" in row.code_context or "orders" in row.code_context, (
        f"Expected entity context in result; got: {row.code_context!r}"
    )


# ---------------------------------------------------------------------------
# T3: qualified entity whose schema has no DB match → degrades to bare match
# ---------------------------------------------------------------------------


def test_qualified_entity_schema_miss_falls_back_to_bare():
    """Code entity has table_name="staging.orders"; only public.orders in DB.

    The qualified key (staging, orders) will not match any DB entry.
    Should fall back to bare name "orders" and match public.orders.
    The result should include a NOTE about multiple-schema ambiguity or
    simply match by bare name — the important thing is no silent drop.
    """
    db_public = _DbEntry("orders", "public")
    knowledge = _knowledge_with_entity("staging.orders", "StagingOrder")
    pipeline = _pipeline()

    results = pipeline._match_tables(knowledge, [db_public])

    # public.orders row must exist
    assert len(results) >= 1, "Expected at least one matched row"

    # Find the orders row and verify entity context is attached
    order_rows = [r for r in results if "orders" in r.table_name]
    assert order_rows, "Expected at least one row matching 'orders'"

    # Entity should be attached somewhere — not silently dropped
    attached = any("StagingOrder" in r.code_context for r in order_rows)
    assert attached, (
        "Qualified-miss should degrade to bare-name match (StagingOrder entity context should "
        "be attached to public.orders row). "
        f"order_rows code contexts: {[r.code_context for r in order_rows]}"
    )


# ---------------------------------------------------------------------------
# T4: two qualified entities, each maps to its own schema — no cross-attach
# ---------------------------------------------------------------------------


def test_two_qualified_entities_each_attach_to_correct_schema():
    """public.orders + analytics.orders in DB.

    Code side: entity_name="PublicOrder" mapped to "public.orders",
               entity_name="AnalyticsOrder" mapped to "analytics.orders".

    Each entity context must attach only to its own schema's row.
    """
    db_public = _DbEntry("orders", "public")
    db_analytics = _DbEntry("orders", "analytics")

    pub_entity = EntityInfo(
        name="PublicOrder",
        table_name="public.orders",
        columns=[ColumnInfo(name="id", col_type="int")],
    )
    ana_entity = EntityInfo(
        name="AnalyticsOrder",
        table_name="analytics.orders",
        columns=[ColumnInfo(name="id", col_type="int")],
    )
    pk = ProjectKnowledge()
    pk.entities["PublicOrder"] = pub_entity
    pk.entities["AnalyticsOrder"] = ana_entity

    pipeline = _pipeline()
    results = pipeline._match_tables(pk, [db_public, db_analytics])

    assert len(results) == 2
    by_display = {r.table_name: r for r in results}

    pub_row = by_display.get("public.orders")
    ana_row = by_display.get("analytics.orders")

    assert pub_row is not None, f"Keys: {list(by_display)}"
    assert ana_row is not None, f"Keys: {list(by_display)}"

    assert "PublicOrder" in pub_row.code_context, (
        f"PublicOrder should be in public.orders context; got: {pub_row.code_context!r}"
    )
    assert "AnalyticsOrder" in ana_row.code_context, (
        f"AnalyticsOrder should be in analytics.orders context; got: {ana_row.code_context!r}"
    )

    # Cross-contamination check
    assert "AnalyticsOrder" not in pub_row.code_context, (
        f"AnalyticsOrder leaked into public.orders: {pub_row.code_context!r}"
    )
    assert "PublicOrder" not in ana_row.code_context, (
        f"PublicOrder leaked into analytics.orders: {ana_row.code_context!r}"
    )
