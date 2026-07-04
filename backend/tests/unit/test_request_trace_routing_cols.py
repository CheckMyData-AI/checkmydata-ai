from __future__ import annotations

from app.models.request_trace import RequestTrace


def test_request_trace_has_routing_columns():
    cols = set(RequestTrace.__table__.columns.keys())
    assert {"route", "complexity", "estimated_queries"} <= cols


def test_routing_column_defaults():
    # server_default.arg is a plain string on SQLite/SQLAlchemy 2 — contains the default value
    assert "unknown" in str(RequestTrace.__table__.c.route.server_default.arg)
    assert "unknown" in str(RequestTrace.__table__.c.complexity.server_default.arg)
    assert "0" in str(RequestTrace.__table__.c.estimated_queries.server_default.arg)
