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
        assert "query_database" in tool_names
        assert "search_codebase" in tool_names
        assert "list_projects" in tool_names
        assert "list_connections" in tool_names
        assert "get_schema" in tool_names
        assert "execute_raw_query" in tool_names
