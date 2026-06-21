"""Unit tests for AlertEvaluator."""

import json

from app.core.alert_evaluator import AlertEvaluator


class TestEvaluateGt:
    def test_triggers_when_above_threshold(self):
        rows = [[150]]
        cols = ["count"]
        conds = json.dumps([{"column": "count", "operator": "gt", "threshold": 100}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["actual_value"] == 150

    def test_does_not_trigger_when_below(self):
        rows = [[50]]
        cols = ["count"]
        conds = json.dumps([{"column": "count", "operator": "gt", "threshold": 100}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 0


class TestEvaluateLt:
    def test_triggers_when_below_threshold(self):
        rows = [[5]]
        cols = ["balance"]
        conds = json.dumps([{"column": "balance", "operator": "lt", "threshold": 10}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1

    def test_does_not_trigger_when_above(self):
        rows = [[15]]
        cols = ["balance"]
        conds = json.dumps([{"column": "balance", "operator": "lt", "threshold": 10}])
        assert len(AlertEvaluator.evaluate(rows, cols, conds)) == 0


class TestEvaluateEq:
    def test_triggers_on_exact_match(self):
        rows = [[0]]
        cols = ["active"]
        conds = json.dumps([{"column": "active", "operator": "eq", "threshold": 0}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1


class TestEvaluateGte:
    def test_triggers_at_threshold(self):
        rows = [[100]]
        cols = ["val"]
        conds = json.dumps([{"column": "val", "operator": "gte", "threshold": 100}])
        assert len(AlertEvaluator.evaluate(rows, cols, conds)) == 1


class TestEvaluateLte:
    def test_triggers_at_threshold(self):
        rows = [[10]]
        cols = ["val"]
        conds = json.dumps([{"column": "val", "operator": "lte", "threshold": 10}])
        assert len(AlertEvaluator.evaluate(rows, cols, conds)) == 1


class TestEvaluatePctChange:
    def test_triggers_on_large_change(self):
        rows = [[100], [150]]
        cols = ["revenue"]
        conds = json.dumps([{"column": "revenue", "operator": "pct_change", "threshold": 30}])
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["actual_value"] == 50.0

    def test_does_not_trigger_on_small_change(self):
        rows = [[100], [105]]
        cols = ["revenue"]
        conds = json.dumps([{"column": "revenue", "operator": "pct_change", "threshold": 30}])
        assert len(AlertEvaluator.evaluate(rows, cols, conds)) == 0

    def test_needs_at_least_two_rows(self):
        rows = [[100]]
        cols = ["revenue"]
        conds = json.dumps([{"column": "revenue", "operator": "pct_change", "threshold": 10}])
        assert len(AlertEvaluator.evaluate(rows, cols, conds)) == 0


class TestEdgeCases:
    def test_none_conditions(self):
        assert AlertEvaluator.evaluate([[1]], ["x"], None) == []

    def test_invalid_json(self):
        assert AlertEvaluator.evaluate([[1]], ["x"], "not json") == []

    def test_empty_rows(self):
        conds = json.dumps([{"column": "x", "operator": "gt", "threshold": 0}])
        assert AlertEvaluator.evaluate([], ["x"], conds) == []

    def test_missing_column(self):
        conds = json.dumps([{"column": "missing", "operator": "gt", "threshold": 0}])
        assert AlertEvaluator.evaluate([[1]], ["x"], conds) == []

    def test_non_numeric_value(self):
        conds = json.dumps([{"column": "name", "operator": "gt", "threshold": 0}])
        assert AlertEvaluator.evaluate([["abc"]], ["name"], conds) == []

    def test_multiple_conditions(self):
        rows = [[200, 5]]
        cols = ["orders", "errors"]
        conds = json.dumps(
            [
                {"column": "orders", "operator": "gt", "threshold": 100},
                {"column": "errors", "operator": "gt", "threshold": 10},
            ]
        )
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["condition"]["column"] == "orders"

    def test_non_numeric_threshold_skips_condition(self):
        # A user-supplied non-numeric threshold must not crash evaluation.
        conds = json.dumps([{"column": "x", "operator": "gt", "threshold": "high"}])
        assert AlertEvaluator.evaluate([[100]], ["x"], conds) == []

    def test_non_numeric_threshold_does_not_abort_other_conditions(self):
        # A bad threshold on one condition must not prevent a later valid
        # condition from being evaluated (skip, don't abort the whole pass).
        rows = [[200, 5]]
        cols = ["orders", "errors"]
        conds = json.dumps(
            [
                {"column": "orders", "operator": "gt", "threshold": "lots"},
                {"column": "errors", "operator": "gt", "threshold": 1},
            ]
        )
        alerts = AlertEvaluator.evaluate(rows, cols, conds)
        assert len(alerts) == 1
        assert alerts[0]["condition"]["column"] == "errors"

    def test_pct_change_non_numeric_threshold_skips(self):
        # The pct_change branch also reads ``threshold`` and must not crash.
        rows = [[100], [200]]
        conds = json.dumps([{"column": "rev", "operator": "pct_change", "threshold": "big"}])
        assert AlertEvaluator.evaluate(rows, ["rev"], conds) == []
