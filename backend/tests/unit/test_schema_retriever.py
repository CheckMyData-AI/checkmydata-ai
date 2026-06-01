"""Unit tests for :class:`SchemaRetriever` (M4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.knowledge.schema_retriever import SchemaRetriever
from app.models.db_index import DbIndex


def _make_entry(
    *,
    table_name: str,
    business_description: str = "",
    data_patterns: str = "",
    column_notes: dict | None = None,
    query_hints: str = "",
    relevance_score: int = 3,
    is_active: bool = True,
) -> DbIndex:
    return DbIndex(
        id=f"id-{table_name}",
        connection_id="conn-1",
        table_name=table_name,
        table_schema="public",
        column_count=len(column_notes or {}),
        row_count=100,
        sample_data_json="[]",
        is_active=is_active,
        relevance_score=relevance_score,
        business_description=business_description,
        data_patterns=data_patterns,
        column_notes_json=json.dumps(column_notes or {}),
        column_distinct_values_json="{}",
        query_hints=query_hints,
        numeric_format_notes="{}",
        code_match_status="unknown",
        code_match_details="",
        indexed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def schema_dir(tmp_path):
    return tmp_path / "bm25"


@pytest.fixture
def small_index(schema_dir):
    """A small representative schema: users, orders, payments."""
    entries = [
        _make_entry(
            table_name="users",
            business_description="Application users and their profile data",
            column_notes={
                "id": "primary key",
                "email": "unique login email",
                "created_at": "signup timestamp",
            },
            query_hints="Join with orders by user_id",
        ),
        _make_entry(
            table_name="orders",
            business_description="Customer orders for the e-commerce checkout flow",
            column_notes={
                "id": "order id",
                "user_id": "foreign key to users",
                "total_cents": "order amount in cents",
                "status": "order status enum",
            },
            data_patterns="Status transitions: pending -> paid -> shipped",
        ),
        _make_entry(
            table_name="payments",
            business_description="Payment transactions linked to orders",
            column_notes={
                "id": "payment id",
                "order_id": "foreign key to orders",
                "amount_cents": "payment amount in cents",
                "provider": "stripe, paypal, etc.",
            },
        ),
    ]
    retriever = SchemaRetriever(data_dir=schema_dir)
    retriever.build("conn-1", indexed_sha="sha-1", entries=entries)
    return retriever


def test_build_persists_snapshot(schema_dir):
    retriever = SchemaRetriever(data_dir=schema_dir)
    entries = [
        _make_entry(table_name="users", business_description="user accounts"),
    ]
    retriever.build("conn-x", indexed_sha="sha-1", entries=entries)
    assert retriever.has_index("conn-x") is True


def test_query_returns_relevant_table_first(small_index):
    hits = small_index.query("conn-1", "show me all customer orders", k=5)
    assert hits, "expected at least one hit"
    assert hits[0]["metadata"]["table_name"] == "orders"


def test_query_matches_business_description(small_index):
    hits = small_index.query("conn-1", "user profile data", k=3)
    assert hits
    assert hits[0]["metadata"]["table_name"] == "users"


def test_query_matches_column_notes(small_index):
    hits = small_index.query("conn-1", "stripe paypal provider", k=3)
    assert hits
    assert hits[0]["metadata"]["table_name"] == "payments"


def test_empty_question_returns_empty(small_index):
    assert small_index.query("conn-1", "") == []
    assert small_index.query("conn-1", "   ") == []


def test_inactive_filter_drops_inactive_tables(schema_dir):
    """``only_active=True`` strips inactive entries from the result set."""
    retriever = SchemaRetriever(data_dir=schema_dir)
    # BM25 IDF zeros out terms appearing in every doc, so we need a few
    # distinct ones to give the query signal.
    entries = [
        _make_entry(
            table_name="legacy_users",
            business_description="deprecated user accounts",
            is_active=False,
        ),
        _make_entry(
            table_name="users",
            business_description="active customer user profiles",
            is_active=True,
        ),
        _make_entry(
            table_name="invoices",
            business_description="billing invoice records",
        ),
        _make_entry(
            table_name="events",
            business_description="audit event log",
        ),
    ]
    retriever.build("conn-2", indexed_sha="sha-1", entries=entries)
    hits = retriever.query("conn-2", "customer user profiles", k=5, only_active=True)
    names = [h["metadata"]["table_name"] for h in hits]
    assert "legacy_users" not in names
    assert "users" in names


def test_only_active_false_returns_inactive_too(schema_dir):
    retriever = SchemaRetriever(data_dir=schema_dir)
    entries = [
        _make_entry(
            table_name="legacy_users",
            business_description="deprecated user accounts",
            is_active=False,
        ),
        _make_entry(
            table_name="invoices",
            business_description="billing invoice records",
        ),
        _make_entry(
            table_name="events",
            business_description="audit event log",
        ),
    ]
    retriever.build("conn-3", indexed_sha="sha-1", entries=entries)
    hits = retriever.query("conn-3", "deprecated user accounts", k=5, only_active=False)
    names = [h["metadata"]["table_name"] for h in hits]
    assert "legacy_users" in names


def test_no_index_returns_empty(schema_dir):
    retriever = SchemaRetriever(data_dir=schema_dir)
    assert retriever.has_index("nope") is False
    assert retriever.query("nope", "anything") == []


def test_delete_removes_snapshot(small_index):
    assert small_index.has_index("conn-1") is True
    small_index.delete("conn-1")
    assert small_index.has_index("conn-1") is False
    assert small_index.query("conn-1", "orders") == []


def test_thirty_table_fixture_recall(schema_dir):
    """Realistic fixture: ranking surfaces the right table among 30 candidates."""
    entries: list[DbIndex] = []
    # Domain-clustered tables so we can test that the retriever doesn't just
    # pick the first match.
    domain = {
        "auth": ["users", "sessions", "api_keys", "password_resets", "two_factor"],
        "billing": [
            "subscriptions",
            "invoices",
            "payments",
            "refunds",
            "credit_notes",
        ],
        "catalog": [
            "products",
            "categories",
            "brands",
            "variants",
            "inventory",
        ],
        "fulfillment": [
            "orders",
            "shipments",
            "deliveries",
            "carriers",
            "tracking_events",
        ],
        "support": [
            "tickets",
            "ticket_messages",
            "agents",
            "macros",
            "kb_articles",
        ],
        "analytics": [
            "events",
            "page_views",
            "conversions",
            "ab_tests",
            "experiments",
        ],
    }
    for area, tables in domain.items():
        for t in tables:
            entries.append(
                _make_entry(
                    table_name=t,
                    business_description=f"{area} domain: {t.replace('_', ' ')}",
                    data_patterns=f"Used by {area} workflows",
                    column_notes={"id": "primary key", "created_at": "timestamp"},
                )
            )

    retriever = SchemaRetriever(data_dir=schema_dir)
    retriever.build("conn-big", indexed_sha="sha-30", entries=entries)

    cases = [
        ("how many active subscriptions do we have", "subscriptions"),
        ("show me all unresolved support tickets", "tickets"),
        ("what page views did we get yesterday", "page_views"),
        ("list refunds issued last month", "refunds"),
        ("inventory by product", "inventory"),
    ]
    for question, expected_table in cases:
        hits = retriever.query("conn-big", question, k=5)
        top_names = [h["metadata"]["table_name"] for h in hits]
        assert expected_table in top_names, (
            f"question={question!r} expected={expected_table!r} top={top_names}"
        )


def test_indexed_sha_freshness_changes_on_rebuild(schema_dir):
    retriever = SchemaRetriever(data_dir=schema_dir)
    e = [_make_entry(table_name="users", business_description="x")]
    retriever.build("conn-f", indexed_sha="sha-A", entries=e)
    retriever.build("conn-f", indexed_sha="sha-B", entries=e)
    # has_index just checks for *any* snapshot; we don't read the sha here.
    # The freshness signal travels through BM25Index._sha_path which is unit-
    # tested in test_bm25_index.py — here we just confirm rebuild succeeds.
    assert retriever.has_index("conn-f") is True


def test_indexes_entries_with_only_table_name(schema_dir):
    """When LLM enrichment is empty, the table name alone still indexes."""
    retriever = SchemaRetriever(data_dir=schema_dir)
    # Multiple docs needed so BM25 IDF gives signal — single-doc corpora
    # collapse to zero scores by design.
    entries = [
        _make_entry(table_name="users"),
        _make_entry(table_name="orders"),
        _make_entry(table_name="invoices"),
    ]
    retriever.build("conn-empty", indexed_sha="sha-1", entries=entries)
    hits = retriever.query("conn-empty", "users")
    names = [h["metadata"]["table_name"] for h in hits]
    assert "users" in names
