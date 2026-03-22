"""Unit tests for audit_log."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.audit import audit_log


@pytest.fixture
def mock_info() -> MagicMock:
    with patch("app.core.audit.audit_logger.info") as m:
        yield m


def test_audit_log_basic(mock_info: MagicMock) -> None:
    audit_log("login")
    mock_info.assert_called_once()
    args, _kwargs = mock_info.call_args
    assert args[0] == ("AUDIT action=%s user=%s project=%s resource=%s/%s detail=%s %s")
    assert args[1:] == ("login", "system", "-", "-", "-", "", "")


def test_audit_log_with_all_params(mock_info: MagicMock) -> None:
    audit_log(
        "delete_row",
        user_id="u1",
        project_id="p9",
        resource_type="table",
        resource_id="t42",
        detail="removed",
    )
    args, _kwargs = mock_info.call_args
    assert args[1:] == ("delete_row", "u1", "p9", "table", "t42", "removed", "")


def test_audit_log_with_extra_kwargs(mock_info: MagicMock) -> None:
    audit_log("export", user_id="u2", ip="1.2.3.4", rows=100)
    args, _kwargs = mock_info.call_args
    assert args[1] == "export"
    assert args[2] == "u2"
    detail_suffix = args[7]
    assert "ip=1.2.3.4" in detail_suffix
    assert "rows=100" in detail_suffix


def test_audit_log_default_values(mock_info: MagicMock) -> None:
    audit_log("noop")
    args, _kwargs = mock_info.call_args
    assert args[2] == "system"
    assert args[3] == "-"


def test_audit_log_with_empty_detail(mock_info: MagicMock) -> None:
    audit_log("ping", detail="")
    args, _kwargs = mock_info.call_args
    assert args[6] == ""
