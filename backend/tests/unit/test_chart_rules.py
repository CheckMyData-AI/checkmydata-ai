"""Tests for consolidated chart selection rules (T15)."""

from __future__ import annotations

from unittest.mock import patch

from app.viz.chart_rules import VALID_VIZ_TYPES, apply_chart_rules


class TestApplyChartRules:
    def test_unknown_type_falls_back_to_table(self):
        out = apply_chart_rules("heatmap", row_count=10, column_count=3)
        assert out.invalid_type is True
        assert out.adjusted_viz_type == "table"
        assert any("Invalid" in w for w in out.warnings)

    @patch("app.viz.chart_rules.settings")
    def test_pie_chart_within_limit_unchanged(self, mock_settings):
        mock_settings.max_pie_categories = 20
        out = apply_chart_rules("pie_chart", row_count=10, column_count=2)
        assert out.adjusted_viz_type == "pie_chart"
        assert out.warnings == []

    @patch("app.viz.chart_rules.settings")
    def test_pie_chart_too_many_slices_falls_back(self, mock_settings):
        mock_settings.max_pie_categories = 20
        out = apply_chart_rules("pie_chart", row_count=100, column_count=2)
        assert out.adjusted_viz_type == "bar_chart"
        assert any("slices" in w for w in out.warnings)

    def test_line_chart_single_column_falls_back(self):
        out = apply_chart_rules("line_chart", row_count=10, column_count=1)
        assert out.adjusted_viz_type == "table"

    def test_bar_chart_single_column_falls_back(self):
        out = apply_chart_rules("bar_chart", row_count=10, column_count=1)
        assert out.adjusted_viz_type == "table"

    def test_scatter_single_column_falls_back(self):
        out = apply_chart_rules("scatter", row_count=10, column_count=1)
        assert out.adjusted_viz_type == "table"

    def test_table_is_always_valid(self):
        out = apply_chart_rules("table", row_count=0, column_count=0)
        assert out.adjusted_viz_type == "table"
        assert out.warnings == []

    def test_all_listed_types_valid(self):
        for t in VALID_VIZ_TYPES:
            out = apply_chart_rules(t, row_count=5, column_count=3)
            assert not out.invalid_type
