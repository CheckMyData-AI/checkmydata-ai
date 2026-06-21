"""Tests for the MCP server package — auth, tools, resources, and server creation."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestMCPAuth:
    @pytest.mark.asyncio
    async def test_api_key_valid_binds_to_configured_user(self):
        from app.mcp_server import auth as auth_mod

        with (
            patch.dict(os.environ, {"CHECKMYDATA_API_KEY": "secret-key-123"}),
            patch.object(auth_mod.settings, "mcp_api_key_user_id", "real-user-1"),
        ):
            user = await auth_mod.resolve_user_from_api_key("secret-key-123")
        assert user["user_id"] == "real-user-1"

    @pytest.mark.asyncio
    async def test_api_key_without_user_binding_is_rejected(self):
        from app.mcp_server import auth as auth_mod

        with (
            patch.dict(os.environ, {"CHECKMYDATA_API_KEY": "secret-key-123"}),
            patch.object(auth_mod.settings, "mcp_api_key_user_id", ""),
        ):
            with pytest.raises(auth_mod.MCPAuthError, match="MCP_API_KEY_USER_ID"):
                await auth_mod.resolve_user_from_api_key("secret-key-123")

    @pytest.mark.asyncio
    async def test_api_key_invalid(self):
        from app.mcp_server.auth import MCPAuthError, resolve_user_from_api_key

        with patch.dict(os.environ, {"CHECKMYDATA_API_KEY": "secret-key-123"}):
            with pytest.raises(MCPAuthError, match="Invalid API key"):
                await resolve_user_from_api_key("wrong-key")

    @pytest.mark.asyncio
    async def test_api_key_not_configured(self):
        from app.mcp_server.auth import MCPAuthError, resolve_user_from_api_key

        excluded = ("CHECKMYDATA_API_KEY", "MCP_API_KEY")
        env = {k: v for k, v in os.environ.items() if k not in excluded}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(MCPAuthError, match="No CHECKMYDATA_API_KEY"):
                await resolve_user_from_api_key("any")

    @pytest.mark.asyncio
    async def test_jwt_valid(self):
        from app.mcp_server.auth import resolve_user_from_jwt

        mock_user = MagicMock()
        mock_user.is_active = True

        with (
            patch("app.mcp_server.auth._auth_svc") as mock_auth,
            patch("app.models.base.async_session_factory") as mock_sf,
        ):
            mock_auth.decode_token.return_value = {"sub": "user-1", "email": "a@b.com"}
            mock_auth.get_by_id = AsyncMock(return_value=mock_user)
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
            user = await resolve_user_from_jwt("valid-token")
        assert user["user_id"] == "user-1"
        assert user["email"] == "a@b.com"

    @pytest.mark.asyncio
    async def test_jwt_invalid(self):
        from app.mcp_server.auth import MCPAuthError, resolve_user_from_jwt

        with patch("app.mcp_server.auth._auth_svc") as mock_auth:
            mock_auth.decode_token.return_value = None
            with pytest.raises(MCPAuthError, match="Invalid or expired JWT"):
                await resolve_user_from_jwt("bad-token")

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials_no_key_fails_closed(self):
        """No per-call credential and no server key => hard failure (no
        anonymous fallback)."""
        from app.mcp_server.auth import MCPAuthError, authenticate

        excluded = ("CHECKMYDATA_API_KEY", "MCP_API_KEY")
        env = {k: v for k, v in os.environ.items() if k not in excluded}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(MCPAuthError, match="authentication required"):
                await authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_uses_server_key_to_bind_user(self):
        """With a server API key + user binding, a credential-less call resolves
        to the bound platform user."""
        from app.mcp_server import auth as auth_mod

        with (
            patch.dict(os.environ, {"CHECKMYDATA_API_KEY": "key"}),
            patch.object(auth_mod.settings, "mcp_api_key_user_id", "bound-user"),
        ):
            user = await auth_mod.authenticate()
        assert user["user_id"] == "bound-user"


# ---------------------------------------------------------------------------
# Tools tests
# ---------------------------------------------------------------------------


_PRINCIPAL = {"user_id": "owner-1", "email": "owner@test.local"}


class TestMCPTools:
    @pytest.mark.asyncio
    async def test_list_projects_scoped_to_caller(self):
        mock_project = MagicMock()
        mock_project.id = "p1"
        mock_project.name = "Test Project"
        mock_project.description = "desc"

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._membership_svc") as mock_msvc:
                mock_msvc.list_accessible = AsyncMock(return_value=[mock_project])
                from app.mcp_server.tools import list_projects

                result = await list_projects(_PRINCIPAL)

        data = json.loads(result)
        assert len(data["projects"]) == 1
        assert data["projects"][0]["id"] == "p1"
        # Scoping must use the caller-aware query, not list_all.
        mock_msvc.list_accessible.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_projects_anonymous_returns_empty(self):
        from app.mcp_server.tools import list_projects

        result = await list_projects({"user_id": ""})
        assert json.loads(result)["projects"] == []

    @pytest.mark.asyncio
    async def test_list_connections_authorized(self):
        mock_conn = MagicMock()
        mock_conn.id = "c1"
        mock_conn.name = "Prod DB"
        mock_conn.db_type = "postgres"
        mock_conn.source_type = "database"
        mock_conn.is_active = True

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._connection_svc") as mock_svc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_svc.list_by_project = AsyncMock(return_value=[mock_conn])
                from app.mcp_server.tools import list_connections

                result = await list_connections(_PRINCIPAL, "p1")

        data = json.loads(result)
        assert len(data["connections"]) == 1
        assert data["connections"][0]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_list_connections_cross_tenant_denied(self):
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._connection_svc") as mock_svc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=False)
                mock_svc.list_by_project = AsyncMock(return_value=[MagicMock()])
                from app.mcp_server.tools import list_connections

                result = await list_connections(_PRINCIPAL, "someone-elses-project")

        data = json.loads(result)
        assert "error" in data
        assert "Access denied" in data["error"]
        # We must never have listed another tenant's connections.
        mock_svc.list_by_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_schema_no_index(self):
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_conn = MagicMock()
            mock_conn.project_id = "p1"
            with (
                patch("app.mcp_server.tools._db_index_svc") as mock_svc,
                patch("app.mcp_server.tools._connection_svc") as mock_csvc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_csvc.get = AsyncMock(return_value=mock_conn)
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_svc.get_index = AsyncMock(return_value=[])
                from app.mcp_server.tools import get_schema

                result = await get_schema(_PRINCIPAL, "c-missing")

        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_get_schema_cross_tenant_denied(self):
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_conn = MagicMock()
            mock_conn.project_id = "other-project"
            with (
                patch("app.mcp_server.tools._db_index_svc") as mock_svc,
                patch("app.mcp_server.tools._connection_svc") as mock_csvc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_csvc.get = AsyncMock(return_value=mock_conn)
                mock_msvc.can_access = AsyncMock(return_value=False)
                mock_svc.get_index = AsyncMock(return_value=[MagicMock()])
                from app.mcp_server.tools import get_schema

                result = await get_schema(_PRINCIPAL, "c1")

        data = json.loads(result)
        assert "Access denied" in data["error"]
        mock_svc.get_index.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_schema_with_entries(self):
        entry = MagicMock()
        entry.table_name = "users"
        entry.table_schema = "public"
        entry.columns_json = json.dumps([{"name": "id", "type": "integer"}])
        entry.row_count = 42
        entry.comment = None

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_conn = MagicMock()
            mock_conn.project_id = "p1"
            with (
                patch("app.mcp_server.tools._db_index_svc") as mock_svc,
                patch("app.mcp_server.tools._connection_svc") as mock_csvc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_csvc.get = AsyncMock(return_value=mock_conn)
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_svc.get_index = AsyncMock(return_value=[entry])
                from app.mcp_server.tools import get_schema

                result = await get_schema(_PRINCIPAL, "c1")

        data = json.loads(result)
        assert len(data["tables"]) == 1
        assert data["tables"][0]["name"] == "users"
        assert data["tables"][0]["row_count"] == 42

    @pytest.mark.asyncio
    async def test_query_database_no_project(self):
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._project_svc") as mock_svc:
                mock_svc.get = AsyncMock(return_value=None)
                from app.mcp_server.tools import query_database

                result = await query_database(_PRINCIPAL, "missing-id", "how many users?")

        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"]

    @pytest.mark.asyncio
    async def test_query_database_cross_tenant_denied(self):
        mock_project = MagicMock()
        mock_project.id = "p1"
        mock_project.name = "Other"

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._project_svc") as mock_svc,
                patch("app.mcp_server.tools._connection_svc") as mock_csvc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_svc.get = AsyncMock(return_value=mock_project)
                mock_msvc.can_access = AsyncMock(return_value=False)
                mock_csvc.list_by_project = AsyncMock(return_value=[MagicMock()])
                from app.mcp_server.tools import query_database

                result = await query_database(_PRINCIPAL, "p1", "how many users?")

        data = json.loads(result)
        assert "Access denied" in data["error"]
        # Denied before touching connections / running the orchestrator.
        mock_csvc.list_by_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_raw_query_not_readonly(self):
        mock_conn = MagicMock()
        mock_conn.id = "c1"
        mock_conn.project_id = "p1"
        mock_conn.is_read_only = False

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._connection_svc") as mock_svc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_svc.get = AsyncMock(return_value=mock_conn)
                mock_msvc.can_access = AsyncMock(return_value=True)
                from app.mcp_server.tools import execute_raw_query

                result = await execute_raw_query(_PRINCIPAL, "c1", "DELETE FROM users")

        data = json.loads(result)
        assert "error" in data
        assert "read-only" in data["error"]

    @pytest.mark.asyncio
    async def test_execute_raw_query_cross_tenant_denied(self):
        mock_conn = MagicMock()
        mock_conn.id = "c1"
        mock_conn.project_id = "other-project"
        mock_conn.is_read_only = True

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._connection_svc") as mock_svc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_svc.get = AsyncMock(return_value=mock_conn)
                mock_msvc.can_access = AsyncMock(return_value=False)
                from app.mcp_server.tools import execute_raw_query

                result = await execute_raw_query(_PRINCIPAL, "c1", "SELECT 1")

        data = json.loads(result)
        assert "Access denied" in data["error"]


# ---------------------------------------------------------------------------
# Resources tests
# ---------------------------------------------------------------------------


class TestMCPResources:
    @pytest.mark.asyncio
    async def test_get_project_rules(self):
        mock_rule = MagicMock()
        mock_rule.id = "r1"
        mock_rule.name = "Revenue rule"
        mock_rule.content = "Revenue = amount * quantity"
        mock_rule.format = "markdown"

        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._rule_svc") as mock_svc,
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_svc.list_all = AsyncMock(return_value=[mock_rule])
                from app.mcp_server.resources import get_project_rules

                result = await get_project_rules(_PRINCIPAL, "p1")

        data = json.loads(result)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["name"] == "Revenue rule"

    @pytest.mark.asyncio
    async def test_get_project_rules_cross_tenant_denied(self):
        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._rule_svc") as mock_svc,
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=False)
                mock_svc.list_all = AsyncMock(return_value=[MagicMock()])
                from app.mcp_server.resources import get_project_rules

                result = await get_project_rules(_PRINCIPAL, "someone-elses-project")

        data = json.loads(result)
        assert "Access denied" in data["error"]
        mock_svc.list_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_project_knowledge_empty(self):
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0

        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
                patch("app.knowledge.vector_store.VectorStore") as mock_vs,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_vs.return_value.get_or_create_collection.return_value = mock_collection
                from app.mcp_server.resources import get_project_knowledge

                result = await get_project_knowledge(_PRINCIPAL, "p1")

        data = json.loads(result)
        assert data["status"] == "empty"
        assert data["document_count"] == 0

    @pytest.mark.asyncio
    async def test_get_project_knowledge_indexed(self):
        mock_collection = MagicMock()
        mock_collection.count.return_value = 150

        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
                patch("app.knowledge.vector_store.VectorStore") as mock_vs,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_vs.return_value.get_or_create_collection.return_value = mock_collection
                from app.mcp_server.resources import get_project_knowledge

                result = await get_project_knowledge(_PRINCIPAL, "p1")

        data = json.loads(result)
        assert data["status"] == "indexed"
        assert data["document_count"] == 150

    @pytest.mark.asyncio
    async def test_get_project_knowledge_cross_tenant_denied(self):
        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.resources._membership_svc") as mock_msvc:
                mock_msvc.can_access = AsyncMock(return_value=False)
                from app.mcp_server.resources import get_project_knowledge

                result = await get_project_knowledge(_PRINCIPAL, "someone-elses-project")

        data = json.loads(result)
        assert "Access denied" in data["error"]

    @pytest.mark.asyncio
    async def test_get_project_schema(self):
        mock_conn = MagicMock()
        mock_conn.id = "c1"
        mock_conn.name = "DB"

        entry = MagicMock()
        entry.table_name = "orders"
        entry.table_schema = "public"
        entry.columns_json = json.dumps([{"name": "id", "type": "int"}])
        entry.row_count = 100

        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._connection_svc") as mock_conn_svc,
                patch("app.mcp_server.resources._db_index_svc") as mock_idx_svc,
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_conn_svc.list_by_project = AsyncMock(return_value=[mock_conn])
                mock_idx_svc.get_index = AsyncMock(return_value=[entry])
                from app.mcp_server.resources import get_project_schema

                result = await get_project_schema(_PRINCIPAL, "p1")

        data = json.loads(result)
        assert len(data["tables"]) == 1
        assert data["tables"][0]["table_name"] == "orders"

    @pytest.mark.asyncio
    async def test_get_project_schema_cross_tenant_denied(self):
        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.resources._connection_svc") as mock_conn_svc,
                patch("app.mcp_server.resources._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=False)
                mock_conn_svc.list_by_project = AsyncMock(return_value=[MagicMock()])
                from app.mcp_server.resources import get_project_schema

                result = await get_project_schema(_PRINCIPAL, "someone-elses-project")

        data = json.loads(result)
        assert "Access denied" in data["error"]
        mock_conn_svc.list_by_project.assert_not_called()

    @pytest.mark.asyncio
    async def test_resources_anonymous_principal_denied(self):
        with patch("app.mcp_server.resources.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.resources._membership_svc") as mock_msvc:
                mock_msvc.can_access = AsyncMock(return_value=True)
                from app.mcp_server.resources import get_project_rules

                result = await get_project_rules({"user_id": ""}, "p1")

        data = json.loads(result)
        assert "Access denied" in data["error"]
        # An empty principal must be denied before any membership lookup.
        mock_msvc.can_access.assert_not_called()


# ---------------------------------------------------------------------------
# Server creation tests
# ---------------------------------------------------------------------------


class TestMCPServerCreation:
    def test_create_mcp_server_returns_fastmcp_instance(self):
        from mcp.server.fastmcp import FastMCP

        from app.mcp_server.server import create_mcp_server

        server = create_mcp_server()
        assert isinstance(server, FastMCP)

    def test_server_has_tools_registered(self):
        from app.mcp_server.server import create_mcp_server

        server = create_mcp_server()
        tool_names = list(server._tool_manager._tools.keys())
        # All public tools must be exposed under the `checkmydata_*` prefix
        # so they cannot collide with another MCP server loaded in parallel.
        for expected in (
            "checkmydata_ping",
            "checkmydata_query_database",
            "checkmydata_search_codebase",
            "checkmydata_list_projects",
            "checkmydata_list_connections",
            "checkmydata_get_schema",
            "checkmydata_execute_raw_query",
        ):
            assert expected in tool_names, f"tool {expected!r} not registered"

    def test_all_tools_carry_annotations(self):
        from app.mcp_server.server import create_mcp_server

        server = create_mcp_server()
        for name, tool in server._tool_manager._tools.items():
            ann = getattr(tool, "annotations", None)
            assert ann is not None, f"{name} is missing ToolAnnotations"
            # Every public tool is read-only — the server never mutates user
            # data; raw SQL is constrained to read-only connections.
            assert ann.readOnlyHint is True, f"{name} should be readOnlyHint=True"
            assert ann.destructiveHint is False, f"{name} should be destructiveHint=False"

    def test_package_exports_factory(self):
        # Convenience import — the package re-exports the factory so callers
        # don't have to dive into the submodule.
        from app.mcp_server import create_mcp_server as exported
        from app.mcp_server.server import create_mcp_server

        assert exported is create_mcp_server


# ---------------------------------------------------------------------------
# Pagination, response format, and ping
# ---------------------------------------------------------------------------


class TestMCPPagination:
    @pytest.mark.asyncio
    async def test_list_projects_paginates(self):
        # 25 projects exceeds the default page size (20) — paging must report
        # has_more=True and a next_offset so the caller can fetch page 2.
        mocks = []
        for i in range(25):
            m = MagicMock()
            m.id = f"p{i}"
            m.name = f"Project {i}"
            m.description = ""
            mocks.append(m)

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._membership_svc") as mock_msvc:
                mock_msvc.list_accessible = AsyncMock(return_value=mocks)
                from app.mcp_server.tools import list_projects

                page1 = await list_projects(_PRINCIPAL, offset=0, limit=20)
                page2 = await list_projects(_PRINCIPAL, offset=20, limit=20)

        data1 = json.loads(page1)
        data2 = json.loads(page2)
        assert data1["count"] == 20
        assert data1["total"] == 25
        assert data1["has_more"] is True
        assert data1["next_offset"] == 20
        assert data2["count"] == 5
        assert data2["has_more"] is False
        assert data2["next_offset"] is None
        # Back-compat alias must keep working.
        assert data1["projects"] == data1["items"]

    @pytest.mark.asyncio
    async def test_list_projects_markdown(self):
        m = MagicMock()
        m.id = "p1"
        m.name = "Test Project"
        m.description = "demo"
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._membership_svc") as mock_msvc:
                mock_msvc.list_accessible = AsyncMock(return_value=[m])
                from app.mcp_server.tools import list_projects

                result = await list_projects(_PRINCIPAL, response_format="markdown")

        # Markdown rendering — must be a string but NOT valid JSON.
        assert "Test Project" in result
        assert "`p1`" in result
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)

    @pytest.mark.asyncio
    async def test_list_connections_paginates(self):
        mocks = []
        for i in range(5):
            c = MagicMock()
            c.id = f"c{i}"
            c.name = f"Conn {i}"
            c.db_type = "postgres"
            c.source_type = "database"
            c.is_active = True
            mocks.append(c)

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("app.mcp_server.tools._connection_svc") as mock_svc,
                patch("app.mcp_server.tools._membership_svc") as mock_msvc,
            ):
                mock_msvc.can_access = AsyncMock(return_value=True)
                mock_svc.list_by_project = AsyncMock(return_value=mocks)
                from app.mcp_server.tools import list_connections

                result = await list_connections(_PRINCIPAL, "p1", offset=2, limit=2)

        data = json.loads(result)
        assert data["count"] == 2
        assert data["total"] == 5
        assert data["offset"] == 2
        assert data["has_more"] is True
        assert data["next_offset"] == 4
        # Back-compat alias.
        assert data["connections"] == data["items"]

    @pytest.mark.asyncio
    async def test_list_clamps_limit(self):
        # Excessive limits get clamped to MAX_PAGE_LIMIT instead of allowing
        # an unbounded response that would blow up the client's context.
        from app.mcp_server.tools import MAX_PAGE_LIMIT, _clamp_pagination

        off, lim = _clamp_pagination(-1, 10_000)
        assert off == 0
        assert lim == MAX_PAGE_LIMIT


class TestMCPPing:
    @pytest.mark.asyncio
    async def test_ping_returns_principal(self):
        from app.mcp_server.tools import ping

        result = await ping(_PRINCIPAL)
        data = json.loads(result)
        assert data["ok"] is True
        assert data["principal"]["user_id"] == "owner-1"


class TestFormatQueryResult:
    """_format_query_result must never silently drop rows or the connector's
    truncation signal — an MCP client agent has to know the result is partial."""

    def _qr(self, n_rows: int, *, truncated: bool = False):
        from app.connectors.base import QueryResult

        return QueryResult(
            columns=["id"],
            rows=[[i] for i in range(n_rows)],
            row_count=n_rows,
            execution_time_ms=1.0,
            truncated=truncated,
        )

    def test_small_result_not_truncated(self):
        from app.mcp_server.tools import _format_query_result

        out = _format_query_result(self._qr(5))
        assert out["returned_rows"] == 5
        assert out["row_count"] == 5
        assert out["truncated"] is False
        assert len(out["rows"]) == 5

    def test_mcp_row_cap_signals_truncation(self):
        from app.mcp_server.tools import MAX_RESULT_ROWS, _format_query_result

        out = _format_query_result(self._qr(MAX_RESULT_ROWS + 50))
        assert len(out["rows"]) == MAX_RESULT_ROWS
        assert out["returned_rows"] == MAX_RESULT_ROWS
        assert out["row_count"] == MAX_RESULT_ROWS + 50
        assert out["truncated"] is True

    def test_connector_truncation_flag_is_propagated(self):
        from app.mcp_server.tools import _format_query_result

        # Connector already truncated (e.g. byte cap) with few rows — the flag
        # must survive even though the MCP 100-row cap was not hit.
        out = _format_query_result(self._qr(10, truncated=True))
        assert len(out["rows"]) == 10
        assert out["truncated"] is True
