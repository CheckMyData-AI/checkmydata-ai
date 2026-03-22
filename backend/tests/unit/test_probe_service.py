"""Unit tests for ProbeService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig, QueryResult
from app.core.data_sanity_checker import DataSanityChecker, SanityWarning
from app.services.probe_service import MAX_PROBE_TABLES, ProbeService


@pytest.fixture
def connection_config() -> ConnectionConfig:
    return ConnectionConfig(db_type="postgresql", db_host="h", db_name="n", ssh_exec_mode=False)


def _make_connector_execute(
    count_rows: int = 10,
    sample_columns: list[str] | None = None,
    sample_rows: list[list] | None = None,
):
    cols = sample_columns or ["id"]
    rows = sample_rows or [[1], [2]]

    async def execute_query(q: str) -> QueryResult:
        if "COUNT" in q.upper():
            return QueryResult(columns=["cnt"], rows=[[count_rows]])
        return QueryResult(columns=cols, rows=rows)

    return execute_query


@pytest.mark.asyncio
async def test_run_probes_respects_max_probe_tables(connection_config: ConnectionConfig):
    tables = [f"t{i}" for i in range(MAX_PROBE_TABLES + 2)]
    connector = AsyncMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.execute_query = AsyncMock(side_effect=_make_connector_execute())

    mock_notes = MagicMock()
    mock_notes.create_note = AsyncMock()

    with (
        patch("app.services.probe_service.get_connector", return_value=connector),
        patch(
            "app.services.session_notes_service.SessionNotesService",
            return_value=mock_notes,
        ),
        patch("app.services.probe_service.DataSanityChecker"),
    ):
        svc = ProbeService()
        session = AsyncMock()
        session.flush = AsyncMock()
        report = await svc.run_probes(
            session,
            "conn-1",
            "proj-1",
            connection_config,
            tables,
        )

    assert len(report) == MAX_PROBE_TABLES
    assert {e["table"] for e in report} == {f"t{i}" for i in range(MAX_PROBE_TABLES)}
    assert connector.execute_query.await_count == MAX_PROBE_TABLES * 2
    connector.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_probes_creates_session_notes_for_findings(connection_config: ConnectionConfig):
    connector = AsyncMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()

    async def execute_query(q: str) -> QueryResult:
        if "COUNT" in q.upper():
            return QueryResult(columns=["cnt"], rows=[[0]])
        return QueryResult(columns=["id"], rows=[])

    connector.execute_query = AsyncMock(side_effect=execute_query)

    mock_notes = MagicMock()
    mock_notes.create_note = AsyncMock()

    with (
        patch("app.services.probe_service.get_connector", return_value=connector),
        patch(
            "app.services.session_notes_service.SessionNotesService",
            return_value=mock_notes,
        ),
        patch("app.services.probe_service.DataSanityChecker"),
    ):
        svc = ProbeService()
        session = AsyncMock()
        session.flush = AsyncMock()
        await svc.run_probes(session, "cid", "pid", connection_config, ["empty_t"])

    mock_notes.create_note.assert_awaited()
    call_kw = mock_notes.create_note.await_args.kwargs
    assert call_kw["connection_id"] == "cid"
    assert call_kw["project_id"] == "pid"
    assert call_kw["category"] == "data_observation"
    assert call_kw["subject"] == "empty_t"
    assert "empty" in call_kw["note"].lower()
    assert call_kw["confidence"] == 0.6


@pytest.mark.asyncio
async def test_run_probes_disconnects_after_error_in_try(connection_config: ConnectionConfig):
    connector = AsyncMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["cnt"], rows=[[0]]),
    )

    mock_notes = MagicMock()
    mock_notes.create_note = AsyncMock(side_effect=RuntimeError("note write failed"))

    with (
        patch("app.services.probe_service.get_connector", return_value=connector),
        patch(
            "app.services.session_notes_service.SessionNotesService",
            return_value=mock_notes,
        ),
        patch("app.services.probe_service.DataSanityChecker"),
    ):
        svc = ProbeService()
        session = AsyncMock()
        session.flush = AsyncMock()
        with pytest.raises(RuntimeError, match="note write failed"):
            await svc.run_probes(session, "c", "p", connection_config, ["t1"])

    connector.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_table_empty_table():
    connector = AsyncMock()
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["cnt"], rows=[[0]]),
    )
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_a", checker)
    assert entry["row_count"] == 0
    assert any("empty" in f.lower() for f in entry["findings"])
    connector.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_table_high_null_rate_column():
    connector = AsyncMock()
    rows = [[None]] * 4 + [[1]]
    call_n = 0

    async def execute_query(q: str) -> QueryResult:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return QueryResult(columns=["cnt"], rows=[[100]])
        return QueryResult(columns=["x"], rows=rows)

    connector.execute_query = AsyncMock(side_effect=execute_query)
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_b", checker)
    assert entry["null_rates"].get("x") == 0.8
    assert any("80%" in f or "NULL" in f for f in entry["findings"])


@pytest.mark.asyncio
async def test_probe_table_count_query_failure():
    connector = AsyncMock()
    connector.execute_query = AsyncMock(side_effect=ConnectionError("count failed"))
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_c", checker)
    assert entry["row_count"] is None
    assert any("count" in f.lower() for f in entry["findings"])
    assert "count failed" in entry["findings"][0]


@pytest.mark.asyncio
async def test_probe_table_sample_query_failure():
    connector = AsyncMock()
    call_n = 0

    async def execute_query(q: str) -> QueryResult:
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            return QueryResult(columns=["cnt"], rows=[[2]])
        raise TimeoutError("sample timeout")

    connector.execute_query = AsyncMock(side_effect=execute_query)
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_d", checker)
    assert entry["row_count"] == 2
    assert any("probe query failed" in f.lower() for f in entry["findings"])
    assert "sample timeout" in entry["findings"][0]


@pytest.mark.asyncio
async def test_probe_table_sanity_checker_warnings():
    connector = AsyncMock()
    connector.execute_query = AsyncMock(
        side_effect=[
            QueryResult(columns=["cnt"], rows=[[1]]),
            QueryResult(columns=["k"], rows=[[1]]),
        ]
    )
    mock_checker = MagicMock(spec=DataSanityChecker)
    mock_checker.check = MagicMock(
        return_value=[
            SanityWarning(
                level="warning",
                check_type="custom_check",
                message="something odd",
            ),
        ],
    )
    svc = ProbeService()
    entry = await svc._probe_table(connector, "tbl_e", mock_checker)
    mock_checker.check.assert_called_once()
    assert any("[custom_check]" in f for f in entry["findings"])
    assert any("something odd" in f for f in entry["findings"])
