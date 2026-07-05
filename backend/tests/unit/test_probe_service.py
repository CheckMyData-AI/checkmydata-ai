"""Unit tests for ProbeService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig, QueryResult
from app.core.data_sanity_checker import DataSanityChecker, SanityWarning
from app.services.probe_service import MAX_PROBE_ROWS, MAX_PROBE_TABLES, ProbeService


@pytest.fixture
def connection_config() -> ConnectionConfig:
    return ConnectionConfig(db_type="postgresql", db_host="h", db_name="n", ssh_exec_mode=False)


def _make_sql_connector(
    count_rows: int = 10,
    sample_columns: list[str] | None = None,
    sample_rows: list[list] | None = None,
    db_type: str = "postgresql",
) -> AsyncMock:
    """Build a fully-configured SQL connector mock for probe tests.

    After the DBIDX-D3 refactor:
    - ``execute_query`` handles only the COUNT query (SQL dialects).
    - ``sample_data`` handles the row sample for ALL dialects.
    """
    cols = sample_columns or ["id"]
    rows = sample_rows or [[1], [2]]

    connector = AsyncMock()
    connector.db_type = db_type
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["cnt"], rows=[[count_rows]])
    )
    connector.sample_data = AsyncMock(return_value=QueryResult(columns=cols, rows=rows))
    return connector


@pytest.mark.asyncio
async def test_run_probes_respects_max_probe_tables(connection_config: ConnectionConfig):
    tables = [f"t{i}" for i in range(MAX_PROBE_TABLES + 2)]
    connector = _make_sql_connector()

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
    # After refactor: execute_query is only for COUNT (1 call per table)
    assert connector.execute_query.await_count == MAX_PROBE_TABLES
    # sample_data is called once per non-empty table
    assert connector.sample_data.await_count == MAX_PROBE_TABLES
    connector.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_probes_creates_session_notes_for_findings(connection_config: ConnectionConfig):
    connector = AsyncMock()
    connector.db_type = "postgresql"
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    # count returns 0 → empty table finding → sample_data never called
    connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[0]]))
    connector.sample_data = AsyncMock(return_value=QueryResult(columns=["id"], rows=[]))

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
    connector.db_type = "postgresql"
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["cnt"], rows=[[0]]),
    )
    connector.sample_data = AsyncMock(return_value=QueryResult(columns=[], rows=[]))

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
    connector.db_type = "postgresql"
    connector.execute_query = AsyncMock(
        return_value=QueryResult(columns=["cnt"], rows=[[0]]),
    )
    connector.sample_data = AsyncMock(return_value=QueryResult(columns=[], rows=[]))
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_a", checker)
    assert entry["row_count"] == 0
    assert any("empty" in f.lower() for f in entry["findings"])
    # count query fired once; sample_data must NOT have been called (early return)
    connector.execute_query.assert_awaited_once()
    connector.sample_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_table_high_null_rate_column():
    connector = AsyncMock()
    connector.db_type = "postgresql"
    rows = [[None]] * 4 + [[1]]
    connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[100]]))
    connector.sample_data = AsyncMock(return_value=QueryResult(columns=["x"], rows=rows))
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_b", checker)
    assert entry["null_rates"].get("x") == 0.8
    assert any("80%" in f or "NULL" in f for f in entry["findings"])


@pytest.mark.asyncio
async def test_probe_table_count_query_failure():
    connector = AsyncMock()
    connector.db_type = "postgresql"
    connector.execute_query = AsyncMock(side_effect=ConnectionError("count failed"))
    connector.sample_data = AsyncMock()
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_c", checker)
    assert entry["row_count"] is None
    assert any("count" in f.lower() for f in entry["findings"])
    assert "count failed" in entry["findings"][0]


@pytest.mark.asyncio
async def test_probe_table_sample_query_failure():
    connector = AsyncMock()
    connector.db_type = "postgresql"
    connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[2]]))
    connector.sample_data = AsyncMock(side_effect=TimeoutError("sample timeout"))
    svc = ProbeService()
    checker = DataSanityChecker()
    entry = await svc._probe_table(connector, "tbl_d", checker)
    assert entry["row_count"] == 2
    assert any("probe query failed" in f.lower() for f in entry["findings"])
    assert "sample timeout" in entry["findings"][0]


@pytest.mark.asyncio
async def test_probe_table_sanity_checker_warnings():
    connector = AsyncMock()
    connector.db_type = "postgresql"
    connector.execute_query = AsyncMock(
        side_effect=[
            QueryResult(columns=["cnt"], rows=[[1]]),
        ]
    )
    connector.sample_data = AsyncMock(
        return_value=QueryResult(columns=["k"], rows=[[1]]),
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


# ---------------------------------------------------------------------------
# MongoDB dialect tests (DBIDX-D3)
# ---------------------------------------------------------------------------


class TestProbeMongo:
    """Verify ProbeService never sends raw SQL strings to a MongoDB connector."""

    @pytest.mark.asyncio
    async def test_probe_uses_sample_data_not_raw_sql(self):
        """sample_data is called; no raw 'SELECT *' reaches execute_query."""
        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.connect = AsyncMock()
        connector.disconnect = AsyncMock()
        # sample path must go via sample_data
        connector.sample_data = AsyncMock(
            return_value=QueryResult(columns=["a"], rows=[[1], [None]])
        )
        # count path: Mongo execute_query accepts a JSON spec for "count"
        connector.execute_query = AsyncMock(
            return_value=QueryResult(columns=["count"], rows=[[10]])
        )

        svc = ProbeService()
        checker = DataSanityChecker()
        await svc._probe_table(connector, "my_coll", checker)

        # sample_data was used
        connector.sample_data.assert_awaited_once()

        # execute_query was called for the count — but must never receive raw SQL
        for call in connector.execute_query.await_args_list:
            raw_arg = call.args[0] if call.args else (call.kwargs.get("query", "") or "")
            assert "SELECT *" not in raw_arg, (
                f"Raw 'SELECT *' SQL sent to Mongo connector: {raw_arg!r}"
            )

    @pytest.mark.asyncio
    async def test_mongo_count_uses_json_spec(self):
        """The count call to execute_query contains a valid Mongo JSON spec."""
        import json as _json

        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.sample_data = AsyncMock(return_value=QueryResult(columns=["x"], rows=[[1]]))
        connector.execute_query = AsyncMock(return_value=QueryResult(columns=["count"], rows=[[5]]))

        svc = ProbeService()
        checker = DataSanityChecker()
        await svc._probe_table(connector, "orders", checker)

        # The execute_query arg must be parseable JSON with the right shape
        assert connector.execute_query.await_count >= 1
        first_arg = connector.execute_query.await_args_list[0].args[0]
        spec = _json.loads(first_arg)  # raises if not valid JSON
        assert spec.get("collection") == "orders"
        assert spec.get("operation") == "count"

    @pytest.mark.asyncio
    async def test_mongo_probe_produces_findings_on_null_columns(self):
        """Null-rate findings are generated for MongoDB collections."""
        # 5 rows, column 'email' is None in 4 out of 5 → 80% null
        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.sample_data = AsyncMock(
            return_value=QueryResult(
                columns=["_id", "email"],
                rows=[[1, None], [2, None], [3, None], [4, None], [5, "ok@test.com"]],
            )
        )
        connector.execute_query = AsyncMock(
            return_value=QueryResult(columns=["count"], rows=[[100]])
        )

        svc = ProbeService()
        checker = DataSanityChecker()
        entry = await svc._probe_table(connector, "users", checker)

        assert entry["null_rates"].get("email") == 0.8
        assert any("NULL" in f or "80%" in f for f in entry["findings"])

    @pytest.mark.asyncio
    async def test_mongo_probe_empty_collection(self):
        """Empty Mongo collection (count=0) produces the 'empty' finding."""
        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.sample_data = AsyncMock(return_value=QueryResult(columns=[], rows=[]))
        connector.execute_query = AsyncMock(return_value=QueryResult(columns=["count"], rows=[[0]]))

        svc = ProbeService()
        checker = DataSanityChecker()
        entry = await svc._probe_table(connector, "empty_coll", checker)

        assert entry["row_count"] == 0
        assert any("empty" in f.lower() for f in entry["findings"])
        # sample_data must NOT have been called (early return after empty count)
        connector.sample_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mongo_count_failure_degrades_gracefully(self):
        """If the count query fails for Mongo, the probe returns a finding and stops."""
        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.execute_query = AsyncMock(side_effect=ConnectionError("mongo down"))
        connector.sample_data = AsyncMock()

        svc = ProbeService()
        checker = DataSanityChecker()
        entry = await svc._probe_table(connector, "broken_coll", checker)

        assert entry["row_count"] is None
        assert any("count" in f.lower() for f in entry["findings"])
        connector.sample_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_probes_mongo_end_to_end(self):
        """run_probes works end-to-end with a Mongo-typed connector (no raw SQL)."""
        connector = AsyncMock()
        connector.db_type = "mongodb"
        connector.connect = AsyncMock()
        connector.disconnect = AsyncMock()
        connector.sample_data = AsyncMock(
            return_value=QueryResult(columns=["_id", "v"], rows=[[1, 10], [2, 20]])
        )
        connector.execute_query = AsyncMock(
            return_value=QueryResult(columns=["count"], rows=[[50]])
        )

        mock_notes = MagicMock()
        mock_notes.create_note = AsyncMock()

        mongo_cfg = ConnectionConfig(
            db_type="mongodb", db_host="localhost", db_name="testdb", ssh_exec_mode=False
        )

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
                session, "conn-m", "proj-m", mongo_cfg, ["col_a", "col_b"]
            )

        assert len(report) == 2
        # No raw SQL reached execute_query
        for call in connector.execute_query.await_args_list:
            raw_arg = call.args[0] if call.args else (call.kwargs.get("query", "") or "")
            assert "SELECT" not in raw_arg.upper(), f"Raw SQL sent to Mongo: {raw_arg!r}"
        connector.sample_data.assert_awaited()


# ---------------------------------------------------------------------------
# SQL-dialect regression: sample_data path equivalence
# ---------------------------------------------------------------------------


class TestProbeSQL:
    """Ensure SQL-dialect probe still works after the dialect-aware refactor."""

    @pytest.mark.asyncio
    async def test_sql_count_still_uses_execute_query(self):
        """For SQL dialects, execute_query is still used for COUNT(*)."""
        connector = AsyncMock()
        connector.db_type = "postgresql"
        connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[7]]))
        connector.sample_data = AsyncMock(return_value=QueryResult(columns=["id"], rows=[[1], [2]]))

        svc = ProbeService()
        checker = DataSanityChecker()
        entry = await svc._probe_table(connector, "my_table", checker)

        assert entry["row_count"] == 7
        # execute_query was called with a COUNT SQL string
        count_calls = [
            c
            for c in connector.execute_query.await_args_list
            if "COUNT" in (c.args[0] if c.args else "").upper()
        ]
        assert count_calls, "No COUNT query found for SQL dialect"

    @pytest.mark.asyncio
    async def test_sql_sample_uses_sample_data_method(self):
        """sample_data() is called (not a raw SELECT * execute_query) for SQL dialects."""
        connector = AsyncMock()
        connector.db_type = "postgresql"
        connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[3]]))
        connector.sample_data = AsyncMock(
            return_value=QueryResult(
                columns=["id", "name"],
                rows=[[1, "Alice"], [2, None], [3, None]],
            )
        )

        svc = ProbeService()
        checker = DataSanityChecker()
        await svc._probe_table(connector, "my_table", checker)

        connector.sample_data.assert_awaited_once_with("my_table", MAX_PROBE_ROWS)
        # No "SELECT *" should have reached execute_query
        for call in connector.execute_query.await_args_list:
            raw = call.args[0] if call.args else ""
            assert "SELECT *" not in raw

    @pytest.mark.asyncio
    async def test_mysql_count_uses_backtick_quoting(self):
        """MySQL identifier quoting (backtick) is preserved in COUNT query."""
        connector = AsyncMock()
        connector.db_type = "mysql"
        connector.execute_query = AsyncMock(return_value=QueryResult(columns=["cnt"], rows=[[5]]))
        connector.sample_data = AsyncMock(return_value=QueryResult(columns=["col"], rows=[[1]]))

        svc = ProbeService()
        checker = DataSanityChecker()
        await svc._probe_table(connector, "orders", checker)

        # Verify backtick quoting in the SQL count call
        count_calls = [
            c
            for c in connector.execute_query.await_args_list
            if "COUNT" in (c.args[0] if c.args else "").upper()
        ]
        assert count_calls
        count_sql = count_calls[0].args[0]
        assert "`orders`" in count_sql
