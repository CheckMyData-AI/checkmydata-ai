"""Tests for expanded DISTINCT collection heuristics and low-cardinality detection."""

from app.connectors.base import ColumnInfo, QueryResult, TableInfo
from app.knowledge.db_index_pipeline import (
    _detect_low_cardinality_columns,
    _is_enum_candidate,
)


class TestIsEnumCandidateNewPatterns:
    """Tests for newly added name patterns and type-based detection."""

    def test_region_column(self):
        assert _is_enum_candidate("region", "varchar", 1000) is True

    def test_locale_column(self):
        assert _is_enum_candidate("locale", "varchar", 500) is True

    def test_stage_column(self):
        assert _is_enum_candidate("order_stage", "varchar", 200) is True

    def test_direction_column(self):
        assert _is_enum_candidate("direction", "varchar", 100) is True

    def test_protocol_column(self):
        assert _is_enum_candidate("protocol", "varchar", 100) is True

    def test_variant_column(self):
        assert _is_enum_candidate("variant", "varchar", 100) is True

    def test_tinyint_type(self):
        assert _is_enum_candidate("processed", "tinyint", 5000) is True

    def test_smallint_type(self):
        assert _is_enum_candidate("flag_col", "smallint", 1000) is True

    def test_int2_type(self):
        assert _is_enum_candidate("data_col", "int2", 500) is True

    def test_tinyint_unsigned(self):
        assert _is_enum_candidate("some_col", "tinyint unsigned", 500) is True

    def test_is_prefix(self):
        assert _is_enum_candidate("is_verified", "integer", 5000) is True

    def test_has_prefix(self):
        assert _is_enum_candidate("has_email", "boolean", 3000) is True

    def test_can_prefix(self):
        assert _is_enum_candidate("can_edit", "int", 1000) is True

    def test_allow_prefix(self):
        assert _is_enum_candidate("allow_notifications", "tinyint", 100) is True

    def test_code_suffix(self):
        assert _is_enum_candidate("country_code", "varchar", 1000) is True

    def test_regular_int_not_matched(self):
        assert _is_enum_candidate("amount", "integer", 5000) is False

    def test_bigint_not_matched(self):
        assert _is_enum_candidate("total_cents", "bigint", 5000) is False

    def test_text_column_not_matched(self):
        assert _is_enum_candidate("description", "text", 1000) is False


class TestDetectLowCardinalityColumns:
    """Tests for sample-data-driven DISTINCT detection."""

    def _make_table(self, *col_specs: tuple[str, str]) -> TableInfo:
        return TableInfo(
            name="test_table",
            columns=[
                ColumnInfo(name=name, data_type=dtype)
                for name, dtype in col_specs
            ],
        )

    def test_detects_binary_flag(self):
        table = self._make_table(
            ("id", "int"), ("processed", "integer"), ("amount", "decimal"),
        )
        result = QueryResult(
            columns=["id", "processed", "amount"],
            rows=[
                [1, 0, 100.50],
                [2, 1, 200.75],
                [3, 0, 50.00],
            ],
            row_count=3,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert "processed" in extra

    def test_skips_already_flagged(self):
        table = self._make_table(("id", "int"), ("status", "varchar"))
        result = QueryResult(
            columns=["id", "status"],
            rows=[[1, "active"], [2, "inactive"], [3, "active"]],
            row_count=3,
        )
        extra = _detect_low_cardinality_columns(result, table, {"status"})
        assert "status" not in extra

    def test_skips_text_columns(self):
        table = self._make_table(("id", "int"), ("notes", "text"))
        result = QueryResult(
            columns=["id", "notes"],
            rows=[[1, "foo"], [2, "bar"], [3, "foo"]],
            row_count=3,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert "notes" not in extra

    def test_skips_json_columns(self):
        table = self._make_table(("id", "int"), ("meta", "json"))
        result = QueryResult(
            columns=["id", "meta"],
            rows=[[1, "{}"], [2, "{}"], [3, "{}"]],
            row_count=3,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert "meta" not in extra

    def test_ignores_high_cardinality(self):
        table = self._make_table(("id", "int"), ("name", "varchar"))
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"], [3, "Charlie"], [4, "Diana"]],
            row_count=4,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert "name" not in extra

    def test_insufficient_rows(self):
        table = self._make_table(("id", "int"), ("flag", "int"))
        result = QueryResult(
            columns=["id", "flag"],
            rows=[[1, 0]],
            row_count=1,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert extra == []

    def test_empty_result(self):
        table = self._make_table(("id", "int"), ("flag", "int"))
        result = QueryResult(columns=[], rows=[], row_count=0)
        extra = _detect_low_cardinality_columns(result, table, set())
        assert extra == []

    def test_detects_string_enum(self):
        table = self._make_table(
            ("id", "int"), ("payment_status", "varchar"),
        )
        result = QueryResult(
            columns=["id", "payment_status"],
            rows=[[1, "paid"], [2, "pending"], [3, "paid"]],
            row_count=3,
        )
        extra = _detect_low_cardinality_columns(result, table, set())
        assert "payment_status" in extra
