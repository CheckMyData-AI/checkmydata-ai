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
    async def test_api_key_valid(self):
        from app.mcp_server.auth import resolve_user_from_api_key

        with patch.dict(os.environ, {"ESIM_API_KEY": "secret-key-123"}):
            user = await resolve_user_from_api_key("secret-key-123")
        assert user["user_id"] == "mcp-api-key-user"

    @pytest.mark.asyncio
    async def test_api_key_invalid(self):
        from app.mcp_server.auth import MCPAuthError, resolve_user_from_api_key

        with patch.dict(os.environ, {"ESIM_API_KEY": "secret-key-123"}):
            with pytest.raises(MCPAuthError, match="Invalid API key"):
                await resolve_user_from_api_key("wrong-key")

    @pytest.mark.asyncio
    async def test_api_key_not_configured(self):
        from app.mcp_server.auth import MCPAuthError, resolve_user_from_api_key

        env = {k: v for k, v in os.environ.items() if k not in ("ESIM_API_KEY", "MCP_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(MCPAuthError, match="No ESIM_API_KEY"):
                await resolve_user_from_api_key("any")

    @pytest.mark.asyncio
    async def test_jwt_valid(self):
        from app.mcp_server.auth import resolve_user_from_jwt

        with patch("app.mcp_server.auth._auth_svc") as mock_auth:
            mock_auth.decode_token.return_value = {"sub": "user-1", "email": "a@b.com"}
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
    async def test_authenticate_no_credentials_no_key(self):
        from app.mcp_server.auth import authenticate

        env = {k: v for k, v in os.environ.items() if k not in ("ESIM_API_KEY", "MCP_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            user = await authenticate()
        assert user["user_id"] == "mcp-anonymous"

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials_key_required(self):
        from app.mcp_server.auth import MCPAuthError, authenticate

        with patch.dict(os.environ, {"ESIM_API_KEY": "key"}):
            with pytest.raises(MCPAuthError, match="Authentication required"):
                await authenticate()


# ---------------------------------------------------------------------------
# Tools tests
# ---------------------------------------------------------------------------


class TestMCPTools:
    @pytest.mark.asyncio
    async def test_list_projects(self):
        mock_project = MagicMock()
        mock_project.id = "p1"
        mock_project.name = "Test Project"
        mock_project.description = "desc"

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._project_svc") as mock_svc:
                mock_svc.list_all = AsyncMock(return_value=[mock_project])
                from app.mcp_server.tools import list_projects

                result = await list_projects()

        data = json.loads(result)
        assert len(data["projects"]) == 1
        assert data["projects"][0]["id"] == "p1"
        assert data["projects"][0]["name"] == "Test Project"

    @pytest.mark.asyncio
    async def test_list_connections(self):
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

            with patch("app.mcp_server.tools._connection_svc") as mock_svc:
                mock_svc.list_by_project = AsyncMock(return_value=[mock_conn])
                from app.mcp_server.tools import list_connections

                result = await list_connections("p1")

        data = json.loads(result)
        assert len(data["connections"]) == 1
        assert data["connections"][0]["id"] == "c1"
        assert data["connections"][0]["db_type"] == "postgres"

    @pytest.mark.asyncio
    async def test_get_schema_no_index(self):
        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._db_index_svc") as mock_svc:
                mock_svc.get_index = AsyncMock(return_value=[])
                from app.mcp_server.tools import get_schema

                result = await get_schema("c-missing")

        data = json.loads(result)
        assert "error" in data

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

            with patch("app.mcp_server.tools._db_index_svc") as mock_svc:
                mock_svc.get_index = AsyncMock(return_value=[entry])
                from app.mcp_server.tools import get_schema

                result = await get_schema("c1")

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

                result = await query_database("missing-id", "how many users?")

        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"]

    @pytest.mark.asyncio
    async def test_execute_raw_query_not_readonly(self):
        mock_conn = MagicMock()
        mock_conn.id = "c1"
        mock_conn.is_read_only = False

        with patch("app.mcp_server.tools.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.mcp_server.tools._connection_svc") as mock_svc:
                mock_svc.get = AsyncMock(return_value=mock_conn)
                from app.mcp_server.tools import execute_raw_query

                result = await execute_raw_query("c1", "DELETE FROM users")

        data = json.loads(result)
        assert "error" in data
        assert "read-only" in data["error"]


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

            with patch("app.mcp_server.resources._rule_svc") as mock_svc:
                mock_svc.list_all = AsyncMock(return_value=[mock_rule])
                from app.mcp_server.resources import get_project_rules

                result = await get_project_rules("p1")

        data = json.loads(result)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["name"] == "Revenue rule"

    @pytest.mark.asyncio
    async def test_get_project_knowledge_empty(self):
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0

        with patch("app.knowledge.vector_store.VectorStore") as mock_vs:
            mock_vs.return_value.get_or_create_collection.return_value = mock_collection
            from app.mcp_server.resources import get_project_knowledge

            result = await get_project_knowledge("p1")

        data = json.loads(result)
        assert data["status"] == "empty"
        assert data["document_count"] == 0

    @pytest.mark.asyncio
    async def test_get_project_knowledge_indexed(self):
        mock_collection = MagicMock()
        mock_collection.count.return_value = 150

        with patch("app.knowledge.vector_store.VectorStore") as mock_vs:
            mock_vs.return_value.get_or_create_collection.return_value = mock_collection
            from app.mcp_server.resources import get_project_knowledge

            result = await get_project_knowledge("p1")

        data = json.loads(result)
        assert data["status"] == "indexed"
        assert data["document_count"] == 150

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
            ):
                mock_conn_svc.list_by_project = AsyncMock(return_value=[mock_conn])
                mock_idx_svc.get_index = AsyncMock(return_value=[entry])
                from app.mcp_server.resources import get_project_schema

                result = await get_project_schema("p1")

        data = json.loads(result)
        assert len(data["tables"]) == 1
        assert data["tables"][0]["table_name"] == "orders"


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
