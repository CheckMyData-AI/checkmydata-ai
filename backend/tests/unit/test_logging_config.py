"""Unit tests for logging formatters and configure_logging."""

import json
import logging
import re
from unittest.mock import patch

from app.core.logging_config import (
    CorrelationFilter,
    JSONFormatter,
    ReadableFormatter,
    configure_logging,
)
from app.core.workflow_tracker import request_id_var, workflow_id_var


def test_correlation_filter_adds_ids() -> None:
    tok_wf = workflow_id_var.set("wf-full-id")
    tok_req = request_id_var.set("req-full-id")
    try:
        flt = CorrelationFilter()
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
        assert flt.filter(record) is True
        assert record.workflow_id == "wf-full-id"
        assert record.request_id == "req-full-id"
    finally:
        workflow_id_var.reset(tok_wf)
        request_id_var.reset(tok_req)


def test_correlation_filter_empty_when_no_vars() -> None:
    flt = CorrelationFilter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
    assert flt.filter(record) is True
    assert record.workflow_id == ""
    assert record.request_id == ""


def test_json_formatter_output_is_valid_json() -> None:
    fmt = JSONFormatter()
    record = logging.LogRecord("pkg.mod", logging.WARNING, __file__, 10, "hello", (), None)
    record.workflow_id = ""
    record.request_id = ""
    out = fmt.format(record)
    data = json.loads(out)
    assert data["level"] == "WARNING"
    assert data["logger"] == "pkg.mod"
    assert data["msg"] == "hello"
    assert "ts" in data


def test_json_formatter_includes_workflow_id() -> None:
    fmt = JSONFormatter()
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", (), None)
    record.workflow_id = "wf-12345"
    record.request_id = ""
    data = json.loads(fmt.format(record))
    assert data["workflow_id"] == "wf-12345"


def test_readable_formatter_basic_format() -> None:
    fmt = ReadableFormatter()
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello world", (), None)
    record.workflow_id = ""
    record.request_id = ""
    out = fmt.format(record)
    assert "INFO" in out
    assert "app:" in out
    assert "hello world" in out
    assert re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}", out)


def test_readable_formatter_with_workflow_id() -> None:
    fmt = ReadableFormatter()
    record = logging.LogRecord("svc", logging.ERROR, __file__, 1, "bad", (), None)
    record.workflow_id = "workflow-identifier-999"
    record.request_id = ""
    out = fmt.format(record)
    assert "[workflow]" in out
    assert "ERROR" in out


def test_configure_logging_sets_level() -> None:
    with patch("app.core.logging_config.logging.config.dictConfig") as mock_dc:
        configure_logging(json_format=False, level="DEBUG")
    cfg = mock_dc.call_args[0][0]
    assert cfg["root"]["level"] == "DEBUG"
