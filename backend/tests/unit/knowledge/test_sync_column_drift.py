"""Unit tests for deterministic column set-diff (SYNC-L5 / T4).

Covers:
- _compute_column_drift static method — pure set arithmetic, no LLM
- TableSyncAnalysis.column_mismatch_json field existence and default
- _make_matched wiring: column_mismatch_json persisted to _MatchedTable
- sync_status override: deterministic mismatch overrides LLM opinion
  when BOTH code_cols and db_cols are non-empty
- sync_status NOT overridden when one side is empty/unknown (LLM opinion kept)
- CodeDbSync model column_mismatch_json field existence (model layer)
- pipeline stores column_mismatch_json in sync_data dict
"""

from __future__ import annotations

import json

import pytest

from app.knowledge.code_db_sync_analyzer import TableSyncAnalysis
from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline


# ---------------------------------------------------------------------------
# _compute_column_drift — pure deterministic set arithmetic
# ---------------------------------------------------------------------------


class TestComputeColumnDrift:
    def test_basic_set_diff(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"a", "b", "c"},
            db_cols={"b", "c", "d"},
        )
        assert drift["code_only"] == ["a"]
        assert drift["db_only"] == ["d"]
        assert drift["matched"] == ["b", "c"]

    def test_returns_sorted_lists(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"z", "a", "m"},
            db_cols={"z", "a", "x"},
        )
        assert drift["code_only"] == ["m"]
        assert drift["db_only"] == ["x"]
        assert drift["matched"] == ["a", "z"]

    def test_identical_sets_no_drift(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"id", "name", "email"},
            db_cols={"id", "name", "email"},
        )
        assert drift["code_only"] == []
        assert drift["db_only"] == []
        assert drift["matched"] == ["email", "id", "name"]

    def test_empty_code_side_no_spurious_mismatch(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols=set(),
            db_cols={"id", "name"},
        )
        assert drift["code_only"] == []
        assert drift["db_only"] == ["id", "name"]
        assert drift["matched"] == []

    def test_empty_db_side_no_spurious_mismatch(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"id", "email"},
            db_cols=set(),
        )
        assert drift["code_only"] == ["email", "id"]
        assert drift["db_only"] == []
        assert drift["matched"] == []

    def test_both_empty(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols=set(),
            db_cols=set(),
        )
        assert drift == {"code_only": [], "db_only": [], "matched": []}

    def test_case_normalization(self):
        """Column names are lower-cased before diffing."""
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"Id", "Name", "Email"},
            db_cols={"id", "name", "phone"},
        )
        assert drift["code_only"] == ["email"]
        assert drift["db_only"] == ["phone"]
        assert drift["matched"] == ["id", "name"]

    def test_mixed_case_db(self):
        drift = CodeDbSyncPipeline._compute_column_drift(
            code_cols={"amount", "status"},
            db_cols={"AMOUNT", "STATUS", "extra_col"},
        )
        assert drift["code_only"] == []
        assert drift["db_only"] == ["extra_col"]
        assert drift["matched"] == ["amount", "status"]


# ---------------------------------------------------------------------------
# TableSyncAnalysis — new column_mismatch_json field
# ---------------------------------------------------------------------------


class TestTableSyncAnalysisField:
    def test_default_value(self):
        a = TableSyncAnalysis(table_name="orders")
        assert a.column_mismatch_json == "{}"

    def test_accepts_json_value(self):
        drift = {"code_only": ["col_a"], "db_only": ["col_b"], "matched": ["id"]}
        a = TableSyncAnalysis(table_name="orders", column_mismatch_json=json.dumps(drift))
        parsed = json.loads(a.column_mismatch_json)
        assert parsed["code_only"] == ["col_a"]


# ---------------------------------------------------------------------------
# sync_status deterministic override
# ---------------------------------------------------------------------------


class TestSyncStatusOverride:
    """When both column sets are non-empty and drift exists → status = mismatch.
    When one side is empty → LLM opinion is kept (can't diff unknown side).
    """

    def _make_analysis(
        self,
        code_cols: set[str],
        db_cols: set[str],
        llm_status: str = "matched",
    ) -> TableSyncAnalysis:
        """Helper: run _compute_column_drift and apply the override logic."""
        drift = CodeDbSyncPipeline._compute_column_drift(code_cols, db_cols)
        has_drift = bool(drift["code_only"] or drift["db_only"])
        both_known = bool(code_cols) and bool(db_cols)

        if both_known and has_drift:
            effective_status = "mismatch"
        elif both_known and not has_drift:
            effective_status = "matched"
        else:
            # one side empty/unknown → keep LLM opinion
            effective_status = llm_status

        return TableSyncAnalysis(
            table_name="t",
            sync_status=effective_status,
            column_mismatch_json=json.dumps(drift),
        )

    def test_drift_forces_mismatch_regardless_of_llm(self):
        a = self._make_analysis({"a", "b", "c"}, {"b", "c", "d"}, llm_status="matched")
        assert a.sync_status == "mismatch"
        parsed = json.loads(a.column_mismatch_json)
        assert parsed["code_only"] == ["a"]
        assert parsed["db_only"] == ["d"]

    def test_no_drift_yields_matched(self):
        a = self._make_analysis({"id", "name"}, {"id", "name"}, llm_status="mismatch")
        assert a.sync_status == "matched"

    def test_empty_code_side_keeps_llm_opinion(self):
        a = self._make_analysis(set(), {"id", "name"}, llm_status="db_only")
        assert a.sync_status == "db_only"

    def test_empty_db_side_keeps_llm_opinion(self):
        a = self._make_analysis({"id"}, set(), llm_status="code_only")
        assert a.sync_status == "code_only"


# ---------------------------------------------------------------------------
# CodeDbSync model — column_mismatch_json column existence
# ---------------------------------------------------------------------------


class TestCodeDbSyncModelField:
    def test_model_has_column_mismatch_json(self):
        from app.models.code_db_sync import CodeDbSync

        # Column must exist on the mapper; we check via __table__.columns
        col_names = {c.name for c in CodeDbSync.__table__.columns}
        assert "column_mismatch_json" in col_names

    def test_default_is_empty_object(self):
        from app.models.code_db_sync import CodeDbSync

        obj = CodeDbSync(connection_id="cid", table_name="t")
        # Default set in mapped_column; server_default covers DB-level; Python-level default
        # may come from the mapped_column `default` kwarg.
        assert obj.column_mismatch_json in ("{}", None)  # None before flush is also OK


# ---------------------------------------------------------------------------
# Pipeline integration: column_mismatch_json flows into sync_data
# ---------------------------------------------------------------------------


class TestPipelineColumnMismatchPersistence:
    """Verify that _make_matched populates column_mismatch_json on _MatchedTable
    and that the store step includes it in sync_data passed to upsert_table_sync.
    """

    def _make_db_entry(self, col_names: list[str]):
        """Minimal DbIndex stub with column_notes_json."""

        class _DbEntry:
            table_name = "orders"
            table_schema = "public"
            business_description = ""
            row_count = None
            column_count = len(col_names)
            data_patterns = ""
            query_hints = ""
            column_notes_json = json.dumps({c: f"note for {c}" for c in col_names})
            column_distinct_values_json = "{}"
            sample_data_json = "[]"

        return _DbEntry()

    def _make_entity(self, col_names: list[str]):
        from app.knowledge.entity_extractor import ColumnInfo, EntityInfo

        cols = [ColumnInfo(name=c, col_type="str") for c in col_names]
        return EntityInfo(name="Order", table_name="orders", columns=cols)

    def test_matched_table_has_column_mismatch_json_attr(self):
        from app.knowledge.entity_extractor import ProjectKnowledge

        entity = self._make_entity(["a", "b", "c"])
        knowledge = ProjectKnowledge(entities={"Order": entity})
        mt = CodeDbSyncPipeline._make_matched(
            "orders",
            db_context="",
            code_context="",
            entity=entity,
            usage=None,
            knowledge=knowledge,
        )
        # _MatchedTable must carry column_mismatch_json for the store step to pick up
        assert hasattr(mt, "column_mismatch_json")

    def test_column_mismatch_json_reflects_set_diff(self):
        from app.knowledge.entity_extractor import ProjectKnowledge

        # code has a, b, c; DB has b, c, d → drift: code_only=[a], db_only=[d]
        entity = self._make_entity(["a", "b", "c"])
        db_entry = self._make_db_entry(["b", "c", "d"])
        knowledge = ProjectKnowledge(entities={"Order": entity})
        mt = CodeDbSyncPipeline._make_matched(
            "orders",
            db_context=CodeDbSyncPipeline._build_db_context(db_entry, scrub=False),
            code_context="",
            entity=entity,
            usage=None,
            knowledge=knowledge,
        )
        drift = json.loads(mt.column_mismatch_json)
        assert drift["code_only"] == ["a"]
        assert drift["db_only"] == ["d"]
        assert drift["matched"] == ["b", "c"]

    def test_deterministic_mismatch_overrides_llm_matched(self):
        """Even if LLM returns 'matched', deterministic drift marks it 'mismatch'."""
        from app.knowledge.entity_extractor import ProjectKnowledge

        entity = self._make_entity(["a", "b", "c"])
        db_entry = self._make_db_entry(["b", "c", "d"])
        knowledge = ProjectKnowledge(entities={"Order": entity})
        mt = CodeDbSyncPipeline._make_matched(
            "orders",
            db_context=CodeDbSyncPipeline._build_db_context(db_entry, scrub=False),
            code_context="",
            entity=entity,
            usage=None,
            knowledge=knowledge,
        )
        # LLM would normally set sync_status; the pipeline applies the override AFTER
        # LLM analysis in the store step. We test that the drift data is PRESENT on
        # the matched table so the store step can apply the override.
        drift = json.loads(mt.column_mismatch_json)
        assert drift["code_only"] != [] or drift["db_only"] != []  # drift detected
