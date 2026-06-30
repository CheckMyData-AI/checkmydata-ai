"""Unit tests for the QueryFailure diagnostics model."""

from __future__ import annotations

import json

from app.models.query_failure import QueryFailure


def test_instantiate_minimal():
    qf = QueryFailure(project_id="p1", failed_sql="SELECT 1", error_type="group_by_violation")
    assert qf.project_id == "p1"
    assert qf.failed_sql == "SELECT 1"
    assert qf.error_type == "group_by_violation"


def test_to_dict_excludes_attempts_by_default():
    qf = QueryFailure(
        id="qf1",
        project_id="p1",
        connection_id="c1",
        db_type="mysql",
        question="cohort analysis",
        failed_sql="SELECT created_at, COUNT(*) FROM t",
        error_type="group_by_violation",
        failure_kind="data_missing",
        raw_error="(1055, ...)",
        attempts_json=json.dumps([{"attempt": 1, "error_type": "group_by_violation"}]),
        attempt_count=1,
        final_status="failed",
    )
    d = qf.to_dict()
    assert d["id"] == "qf1"
    assert d["error_type"] == "group_by_violation"
    assert d["final_status"] == "failed"
    assert "attempts" not in d  # summary view omits the heavy field


def test_to_dict_includes_attempts_when_requested():
    qf = QueryFailure(
        project_id="p1",
        attempts_json=json.dumps([{"attempt": 1}, {"attempt": 2}]),
        attempt_count=2,
    )
    d = qf.to_dict(include_attempts=True)
    assert d["attempts"] == [{"attempt": 1}, {"attempt": 2}]


def test_to_dict_attempts_tolerates_bad_json():
    qf = QueryFailure(project_id="p1", attempts_json="not json")
    assert qf.to_dict(include_attempts=True)["attempts"] == []
