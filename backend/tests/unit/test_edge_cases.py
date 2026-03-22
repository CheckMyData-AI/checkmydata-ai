"""Edge-case tests across multiple modules."""

import json

from app.core.alert_evaluator import AlertEvaluator


class TestAlertEvaluatorEdgeCases:
    def test_null_threshold_skipped(self):
        conds = json.dumps([{"column": "x", "operator": "gt", "threshold": None}])
        assert AlertEvaluator.evaluate([[10]], ["x"], conds) == []

    def test_pct_change_prev_zero_skipped(self):
        rows = [[0], [100]]
        cols = ["val"]
        conds = json.dumps([{"column": "val", "operator": "pct_change", "threshold": 10}])
        assert AlertEvaluator.evaluate(rows, cols, conds) == []

    def test_unknown_operator_skipped(self):
        conds = json.dumps([{"column": "x", "operator": "neq", "threshold": 5}])
        assert AlertEvaluator.evaluate([[10]], ["x"], conds) == []

    def test_conditions_not_a_list(self):
        conds = json.dumps({"column": "x", "operator": "gt", "threshold": 5})
        assert AlertEvaluator.evaluate([[10]], ["x"], conds) == []

    def test_pct_change_non_numeric_values(self):
        rows = [["abc"], ["def"]]
        cols = ["val"]
        conds = json.dumps([{"column": "val", "operator": "pct_change", "threshold": 10}])
        assert AlertEvaluator.evaluate(rows, cols, conds) == []

    def test_pct_change_negative_threshold(self):
        rows = [[100], [50]]
        cols = ["revenue"]
        conds = json.dumps(
            [
                {
                    "column": "revenue",
                    "operator": "pct_change",
                    "threshold": 30,
                }
            ]
        )
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["actual_value"] == -50.0

    def test_multiple_rows_only_first_match_triggers(self):
        rows = [[200], [50], [300]]
        cols = ["val"]
        conds = json.dumps([{"column": "val", "operator": "gt", "threshold": 100}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["actual_value"] == 200

    def test_empty_column_name_skipped(self):
        conds = json.dumps([{"column": "", "operator": "gt", "threshold": 5}])
        assert AlertEvaluator.evaluate([[10]], ["x"], conds) == []

    def test_index_error_in_row_skipped(self):
        rows = [[]]
        cols = ["x"]
        conds = json.dumps([{"column": "x", "operator": "gt", "threshold": 5}])
        assert AlertEvaluator.evaluate(rows, cols, conds) == []

    def test_float_threshold_string(self):
        conds = json.dumps([{"column": "x", "operator": "gt", "threshold": "99.5"}])
        alerts = AlertEvaluator.evaluate([[100]], ["x"], conds)
        assert len(alerts) == 1
