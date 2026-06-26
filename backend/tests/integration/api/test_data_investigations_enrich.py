"""Tests for investigation enrichment (task T9)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.data_investigations import _enrich_sync_from_investigation
from app.models.data_validation import DataInvestigation


@pytest.mark.asyncio
async def test_missing_filter_routes_to_recommendations(monkeypatch, db_session: AsyncSession):
    """Assert missing_filter routes to query_recommendations, not required_filters_json."""
    captured = {}

    async def _fake_enrichment(self, db, *, connection_id, table_name, field, value):
        """Capture the field and value arguments."""
        captured["field"] = field
        captured["value"] = value

    monkeypatch.setattr(
        "app.services.code_db_sync_service.CodeDbSyncService.add_runtime_enrichment",
        _fake_enrichment,
    )

    # Build a mock investigation with root_cause_category="missing_filter"
    inv = DataInvestigation(
        id="test-inv-001",
        connection_id="test-conn-001",
        session_id="test-session-001",
        trigger_message_id="test-msg-001",
        original_query="SELECT * FROM users WHERE status = 'active'",
        original_result_summary='{"count": 100}',
        user_complaint_type="missing_data",
        user_complaint_detail="Some records missing",
        user_expected_value="150 records",
        problematic_column=None,
        corrected_query=None,
        corrected_result_json=None,
        root_cause="Missing filter: WHERE region_id = 5",
        root_cause_category="missing_filter",
        status="completed",
        phase="investigating",
        investigation_log_json="[]",
    )

    # Call the enrichment function
    await _enrich_sync_from_investigation(db_session, inv)

    # Assert the field is query_recommendations, not required_filters_json
    assert captured.get("field") == "query_recommendations"
    assert "[from investigation]" in captured.get("value", "")
    assert "Missing filter: WHERE region_id = 5" in captured.get("value", "")
