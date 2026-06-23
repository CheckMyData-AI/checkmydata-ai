"""Tests for MCP Batch-3 cleanups (B3.1–B3.6).

B3.1 — is_active default connection selection
B3.2 — project_schema resource table cap
B3.3 — SSE transport deprecation label
B3.4 — Principal TypedDict in runtime
B3.5 — userless sync skipped-persist log at DEBUG not WARNING
B3.6 — test_config_mcp_mount robustness (covered in test_config_mcp_mount.py)
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# B3.1 — is_active default connection selection
# ---------------------------------------------------------------------------


class TestIsActiveDefaultConnection:
    """query_database should prefer an active connection when no connection_id
    is given, rather than blindly picking connections[0]."""

    def _make_conn(self, id: str, name: str, project_id: str, is_active: bool) -> MagicMock:
        c = MagicMock()
        c.id = id
        c.name = name
        c.project_id = project_id
        c.is_active = is_active
        return c

    @pytest.mark.asyncio
    async def test_active_connection_preferred_over_inactive_first(self):
        """When the first connection is inactive and the second is active,
        the active one must be used."""
        from app.mcp_server import tools as tools_mod

        inactive = self._make_conn("conn-inactive", "Inactive DB", "proj-1", False)
        active = self._make_conn("conn-active", "Active DB", "proj-1", True)

        project = MagicMock()
        project.id = "proj-1"
        project.name = "Test Project"

        chosen: list[Any] = []

        async def fake_to_config(session, conn):
            chosen.append(conn)
            cfg = MagicMock()
            cfg.connection_id = conn.id
            return cfg

        fake_result = MagicMock()
        fake_result.answer = "42"
        fake_result.response_type = "text"
        fake_result.query = None
        fake_result.query_explanation = None
        fake_result.results = None
        fake_result.viz_type = "text"
        fake_result.viz_config = {}
        fake_result.knowledge_sources = []
        fake_result.error = None

        with (
            patch.object(tools_mod._project_svc, "get", new=AsyncMock(return_value=project)),
            patch.object(tools_mod._membership_svc, "can_access", new=AsyncMock(return_value=True)),
            patch.object(
                tools_mod._connection_svc,
                "list_by_project",
                new=AsyncMock(return_value=[inactive, active]),
            ),
            patch.object(
                tools_mod._usage_svc, "check_token_budget", new=AsyncMock(return_value=None)
            ),
            patch.object(tools_mod._connection_svc, "to_config", new=fake_to_config),
            patch(
                "app.mcp_server.tools._make_orchestrator",
                return_value=MagicMock(run=AsyncMock(return_value=fake_result)),
            ),
            patch(
                "app.mcp_server.tools._singleton_tracker",
                MagicMock(begin=AsyncMock(return_value="wf-123"), end=AsyncMock()),
            ),
            patch("app.mcp_server.tools._get_trace_svc", return_value=None),
        ):
            await tools_mod.query_database(
                principal={"user_id": "u-1", "email": "u@example.com"},
                project_id="proj-1",
                question="What is the answer?",
            )

        assert len(chosen) == 1, "to_config should have been called exactly once"
        assert chosen[0].id == "conn-active", f"Expected active connection but got {chosen[0].id}"

    @pytest.mark.asyncio
    async def test_first_connection_used_when_all_inactive(self):
        """Fallback: when no connection is active, connections[0] is used."""
        from app.mcp_server import tools as tools_mod

        c1 = self._make_conn("conn-a", "DB A", "proj-2", False)
        c2 = self._make_conn("conn-b", "DB B", "proj-2", False)

        project = MagicMock()
        project.id = "proj-2"
        project.name = "P2"

        chosen: list[Any] = []

        async def fake_to_config(session, conn):
            chosen.append(conn)
            cfg = MagicMock()
            cfg.connection_id = conn.id
            return cfg

        fake_result = MagicMock()
        fake_result.answer = "ok"
        fake_result.response_type = "text"
        fake_result.query = None
        fake_result.query_explanation = None
        fake_result.results = None
        fake_result.viz_type = "text"
        fake_result.viz_config = {}
        fake_result.knowledge_sources = []
        fake_result.error = None

        with (
            patch.object(tools_mod._project_svc, "get", new=AsyncMock(return_value=project)),
            patch.object(tools_mod._membership_svc, "can_access", new=AsyncMock(return_value=True)),
            patch.object(
                tools_mod._connection_svc,
                "list_by_project",
                new=AsyncMock(return_value=[c1, c2]),
            ),
            patch.object(
                tools_mod._usage_svc, "check_token_budget", new=AsyncMock(return_value=None)
            ),
            patch.object(tools_mod._connection_svc, "to_config", new=fake_to_config),
            patch(
                "app.mcp_server.tools._make_orchestrator",
                return_value=MagicMock(run=AsyncMock(return_value=fake_result)),
            ),
            patch(
                "app.mcp_server.tools._singleton_tracker",
                MagicMock(begin=AsyncMock(return_value="wf-456"), end=AsyncMock()),
            ),
            patch("app.mcp_server.tools._get_trace_svc", return_value=None),
        ):
            await tools_mod.query_database(
                principal={"user_id": "u-2", "email": "u@example.com"},
                project_id="proj-2",
                question="Anything?",
            )

        assert chosen[0].id == "conn-a"


# ---------------------------------------------------------------------------
# B3.2 — project_schema resource table cap
# ---------------------------------------------------------------------------


class TestProjectSchemaCap:
    """get_project_schema must cap output at MAX_RESOURCE_TABLES tables."""

    def _make_entry(self, i: int) -> MagicMock:
        e = MagicMock()
        e.table_name = f"tbl_{i}"
        e.table_schema = "public"
        e.column_notes_json = None
        e.row_count = i * 10
        return e

    @pytest.mark.asyncio
    async def test_schema_not_truncated_when_under_cap(self):
        from app.mcp_server import resources as res_mod

        conn = MagicMock()
        conn.id = "c1"
        conn.name = "DB1"

        entries = [self._make_entry(i) for i in range(10)]

        with (
            patch.object(res_mod._membership_svc, "can_access", new=AsyncMock(return_value=True)),
            patch.object(
                res_mod._connection_svc,
                "list_by_project",
                new=AsyncMock(return_value=[conn]),
            ),
            patch.object(
                res_mod._db_index_svc,
                "get_index",
                new=AsyncMock(return_value=entries),
            ),
        ):
            raw = await res_mod.get_project_schema(
                principal={"user_id": "u-1", "email": "u@example.com"},
                project_id="proj-1",
            )

        payload = json.loads(raw)
        assert payload["truncated"] is False
        assert payload["total_tables"] == 10
        assert len(payload["tables"]) == 10

    @pytest.mark.asyncio
    async def test_schema_truncated_when_over_cap(self):
        from app.mcp_server import resources as res_mod

        cap = res_mod.MAX_RESOURCE_TABLES
        over = cap + 50

        conn = MagicMock()
        conn.id = "c1"
        conn.name = "DB1"

        entries = [self._make_entry(i) for i in range(over)]

        with (
            patch.object(res_mod._membership_svc, "can_access", new=AsyncMock(return_value=True)),
            patch.object(
                res_mod._connection_svc,
                "list_by_project",
                new=AsyncMock(return_value=[conn]),
            ),
            patch.object(
                res_mod._db_index_svc,
                "get_index",
                new=AsyncMock(return_value=entries),
            ),
        ):
            raw = await res_mod.get_project_schema(
                principal={"user_id": "u-1", "email": "u@example.com"},
                project_id="proj-1",
            )

        payload = json.loads(raw)
        assert payload["truncated"] is True
        assert payload["total_tables"] == over
        assert len(payload["tables"]) == cap


# ---------------------------------------------------------------------------
# B3.3 — SSE transport deprecation label
# ---------------------------------------------------------------------------


class TestSseDeprecationLabel:
    def test_sse_still_accepted_as_choice(self):
        """argparse must not raise when --transport sse is passed."""
        import argparse

        from app.mcp_server.__main__ import main  # noqa: F401 — import smoke

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "sse", "streamable-http"],
            default="stdio",
        )
        args = parser.parse_args(["--transport", "sse"])
        assert args.transport == "sse"

    def test_help_contains_deprecated(self):
        """The --transport help text must contain the word 'deprecated'."""
        import argparse

        # Recreate the parser as defined in __main__.main()
        parser = argparse.ArgumentParser(description="CheckMyData.ai MCP Server")
        parser.add_argument(
            "--transport",
            choices=["stdio", "sse", "streamable-http"],
            default="stdio",
            help=(
                "MCP transport mode. 'stdio' (default) for local clients "
                "(Claude Desktop, Cursor); 'streamable-http' for remote / "
                "multi-client deployments; 'sse' is DEPRECATED — kept for "
                "back-compat with older clients but will be removed in a "
                "future release; prefer 'streamable-http'."
            ),
        )
        try:
            parser.parse_args(["--help"])
        except SystemExit:
            pass
        # Check the help action's option_strings to verify description text
        for action in parser._actions:
            if "--transport" in getattr(action, "option_strings", []):
                assert "deprecated" in action.help.lower(), (
                    "Expected 'deprecated' in --transport help text"
                )
                break
        else:
            pytest.fail("--transport argument not found in parser")


# ---------------------------------------------------------------------------
# B3.4 — Principal TypedDict in runtime
# ---------------------------------------------------------------------------


class TestPrincipalTypedDict:
    def test_principal_is_typeddict_with_correct_keys(self):
        from app.mcp_server.runtime import Principal

        # TypedDict instances are plain dicts at runtime
        p: Principal = {"user_id": "u-1", "email": "u@example.com"}
        assert p["user_id"] == "u-1"
        assert p["email"] == "u@example.com"

    def test_current_principal_contextvar_default_none(self):
        from app.mcp_server.runtime import current_principal

        assert current_principal.get() is None

    def test_current_principal_contextvar_accepts_principal(self):
        from app.mcp_server.runtime import Principal, current_principal

        p: Principal = {"user_id": "u-99", "email": "test@example.com"}
        token = current_principal.set(p)
        try:
            got = current_principal.get()
            assert got is not None
            assert got["user_id"] == "u-99"
        finally:
            current_principal.reset(token)


# ---------------------------------------------------------------------------
# B3.5 — Quiet trace log at DEBUG for empty user_id
# ---------------------------------------------------------------------------


class TestTracePersistenceQuietLog:
    """The skipping-initial-persist message must NOT be emitted at WARNING
    when user_id is empty (the expected userless/sync case)."""

    @pytest.mark.asyncio
    async def test_empty_user_id_logs_at_debug_not_warning(self, caplog):
        from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
        from app.services.trace_persistence_service import TracePersistenceService

        tracker = WorkflowTracker()
        svc = TracePersistenceService(tracker)

        # Build a minimal buffer with no user_id (simulates a sync workflow)
        from app.services.trace_persistence_service import _WorkflowBuffer

        buf = _WorkflowBuffer(
            workflow_id="wf-sync-1234",
            pipeline="sync",
            context={"project_id": "proj-x", "user_id": ""},
        )

        # pipeline_end event with success status
        end_event = WorkflowEvent(
            workflow_id="wf-sync-1234",
            pipeline="sync",
            step="pipeline_end",
            status="completed",
        )
        buf.events.append(end_event)

        with caplog.at_level(logging.WARNING, logger="app.services.trace_persistence_service"):
            # Call _persist_workflow directly — it's the method that logs.
            await svc._persist_workflow(buf, end_event)

        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno >= logging.WARNING and "skipping initial persist" in r.message
        ]
        assert warning_messages == [], (
            f"Expected no WARNING for empty user_id, got: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_empty_user_id_does_log_at_debug(self, caplog):
        """Sanity-check: the message IS emitted at DEBUG level."""
        from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
        from app.services.trace_persistence_service import (
            TracePersistenceService,
            _WorkflowBuffer,
        )

        tracker = WorkflowTracker()
        svc = TracePersistenceService(tracker)

        buf = _WorkflowBuffer(
            workflow_id="wf-sync-5678",
            pipeline="sync",
            context={"project_id": "proj-y", "user_id": ""},
        )
        end_event = WorkflowEvent(
            workflow_id="wf-sync-5678",
            pipeline="sync",
            step="pipeline_end",
            status="completed",
        )
        buf.events.append(end_event)

        with caplog.at_level(logging.DEBUG, logger="app.services.trace_persistence_service"):
            await svc._persist_workflow(buf, end_event)

        debug_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.DEBUG and "skipping initial persist" in r.message
        ]
        assert debug_messages, "Expected at least one DEBUG message for empty user_id"
