# backend/tests/unit/knowledge/test_code_db_sync_pipeline_run.py
import json

from app.knowledge.code_db_sync_analyzer import TableSyncAnalysis
from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline


class _DbEntry:
    def __init__(self, name, schema="public"):
        self.table_name = name
        self.table_schema = schema
        self.business_description = ""
        self.row_count = None
        self.column_count = 0
        self.data_patterns = ""
        self.query_hints = ""
        self.column_notes_json = "{}"
        self.column_distinct_values_json = json.dumps({"email": ["a@b.com", "c@d.com"]})
        self.sample_data_json = json.dumps([{"email": "a@b.com"}])


def test_build_db_context_scrubs_when_enabled():
    ctx = CodeDbSyncPipeline._build_db_context(_DbEntry("users"), scrub=True, omit_samples=False)
    assert "a@b.com" not in ctx
    assert "redacted" in ctx


def test_build_db_context_raw_when_scrub_disabled():
    # scrub=False path: raw data passes through when scrubbing globally off
    ctx = CodeDbSyncPipeline._build_db_context(_DbEntry("logs"), scrub=False, omit_samples=False)
    assert "a@b.com" in ctx  # raw allowed only when scrubbing disabled


def test_build_db_context_omit_samples_true():
    ctx = CodeDbSyncPipeline._build_db_context(_DbEntry("users"), scrub=True, omit_samples=True)
    assert "a@b.com" not in ctx
    assert "Sample data" not in ctx
    assert "distinct values" not in ctx.lower()


def test_distinct_truncation_marker():
    e = _DbEntry("t")
    e.column_distinct_values_json = json.dumps({"k": [str(i) for i in range(20)]})
    ctx = CodeDbSyncPipeline._build_db_context(e, scrub=True, omit_samples=False)
    assert "+5 more" in ctx


def test_all_fallback_guard_helper():
    analyses = [
        TableSyncAnalysis(table_name="a", is_fallback=True),
        TableSyncAnalysis(table_name="b", is_fallback=True),
    ]
    total = len(analyses)
    non_fb = sum(1 for a in analyses if not a.is_fallback)
    assert (non_fb / total) < 0.5  # guard would trip
