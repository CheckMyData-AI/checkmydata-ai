"""Unit tests for StageExecutor._parse_process_data_params."""

from __future__ import annotations

import json

from app.agents.stage_context import PlanStage
from app.agents.stage_executor import StageExecutor
from app.connectors.base import QueryResult


def _make_stage(
    description: str = "",
    input_context: str = "",
    depends_on: list[str] | None = None,
) -> PlanStage:
    return PlanStage(
        stage_id="test",
        description=description,
        tool="process_data",
        depends_on=depends_on or [],
        input_context=input_context,
    )


def _make_qr(columns: list[str]) -> QueryResult:
    return QueryResult(columns=columns, rows=[], row_count=0)


class TestParseProcessDataParams:
    def test_json_input_context_parsed(self):
        ctx = json.dumps({"operation": "ip_to_country", "column": "user_ip"})
        stage = _make_stage(input_context=ctx)
        qr = _make_qr(["user_ip", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "ip_to_country"
        assert params["column"] == "user_ip"

    def test_json_aggregate_data(self):
        ctx = json.dumps(
            {
                "operation": "aggregate_data",
                "group_by": ["country"],
                "aggregations": {"amount": "sum", "*": "count"},
            }
        )
        stage = _make_stage(input_context=ctx)
        qr = _make_qr(["country", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "aggregate_data"
        assert params["group_by"] == ["country"]
        assert isinstance(params["aggregations"], list)
        assert ("amount", "sum") in params["aggregations"]
        assert ("*", "count") in params["aggregations"]

    def test_json_aggregate_list_format(self):
        ctx = json.dumps(
            {
                "operation": "aggregate_data",
                "group_by": ["country"],
                "aggregations": [["amount", "sum"], ["amount", "avg"], ["*", "count"]],
            }
        )
        stage = _make_stage(input_context=ctx)
        qr = _make_qr(["country", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "aggregate_data"
        assert isinstance(params["aggregations"], list)
        assert len(params["aggregations"]) == 3

    def test_heuristic_ip_from_description(self):
        stage = _make_stage(
            description="Convert IP addresses to countries",
            input_context="resolve IPs",
        )
        qr = _make_qr(["user_ip", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "filter_data"

    def test_no_heuristic_phone_defaults_to_filter(self):
        stage = _make_stage(
            description="Convert phone numbers to destination countries",
            input_context="",
        )
        qr = _make_qr(["phone_number", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "filter_data"

    def test_no_heuristic_aggregate_defaults_to_filter(self):
        stage = _make_stage(
            description="Group and aggregate results by country",
            input_context="",
        )
        qr = _make_qr(["country", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "filter_data"

    def test_fallback_to_filter_data(self):
        stage = _make_stage(description="Process the data", input_context="")
        qr = _make_qr(["some_ip", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "filter_data"

    def test_invalid_json_falls_back_to_heuristic(self):
        stage = _make_stage(
            description="ip resolution",
            input_context="not valid json {{{",
        )
        qr = _make_qr(["client_ip", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)

        assert params["operation"] == "filter_data"

    def test_no_column_without_explicit_context(self):
        stage = _make_stage(
            description="Convert IPs",
            input_context="",
        )
        qr = _make_qr(["address", "amount"])

        params = StageExecutor._parse_process_data_params(stage, qr)
        assert "column" not in params
