"""Unit tests for ConnectionService."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.services.connection_service import ConnectionService
from app.services.encryption import decrypt

svc = ConnectionService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


class TestConnectionCreate:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="My PG",
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
        )
        assert conn.id is not None
        assert conn.name == "My PG"
        assert conn.db_type == "postgresql"
        assert conn.project_id == proj.id

    @pytest.mark.asyncio
    async def test_create_encrypts_password(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="Encrypted",
            db_type="mysql",
            db_port=3306,
            db_name="mydb",
            db_password="secret123",
        )
        assert conn.db_password_encrypted is not None
        assert conn.db_password_encrypted != "secret123"

    @pytest.mark.asyncio
    async def test_create_encrypts_connection_string(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="ConnStr",
            db_type="postgresql",
            db_port=5432,
            db_name="mydb",
            connection_string="postgresql://user:pass@host/db",
        )
        assert conn.connection_string_encrypted is not None
        assert "postgresql://" not in (conn.connection_string_encrypted or "")

    @pytest.mark.asyncio
    async def test_create_serializes_ssh_pre_commands(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH",
            db_type="postgresql",
            db_port=5432,
            db_name="mydb",
            ssh_pre_commands=["source /env.sh", "export FOO=bar"],
        )
        assert conn.ssh_pre_commands == json.dumps(["source /env.sh", "export FOO=bar"])

    @pytest.mark.asyncio
    async def test_create_serializes_mcp_args(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP",
            db_type="mcp",
            db_port=0,
            db_name="",
            source_type="mcp",
            mcp_server_args=["--stdio", "--debug"],
        )
        assert conn.mcp_server_args == json.dumps(["--stdio", "--debug"])

    @pytest.mark.asyncio
    async def test_create_encrypts_mcp_env(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP Env",
            db_type="mcp",
            db_port=0,
            db_name="",
            mcp_env={"API_KEY": "secret"},
        )
        assert conn.mcp_env_encrypted is not None

    @pytest.mark.asyncio
    async def test_create_sanitizes_whitespace(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="  Spaced Name  ",
            db_type="postgresql",
            db_host="  db.example.com  ",
            db_port=5432,
            db_name="mydb",
            ssh_host="  ssh.example.com\t",
            ssh_user="  admin  ",
        )
        assert conn.name == "Spaced Name"
        assert conn.db_host == "db.example.com"
        assert conn.ssh_host == "ssh.example.com"
        assert conn.ssh_user == "admin"


class TestConnectionGet:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="GetMe", db_type="pg", db_port=5432, db_name="db"
        )
        fetched = await svc.get(db, conn.id)
        assert fetched is not None
        assert fetched.id == conn.id
        assert fetched.name == "GetMe"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        result = await svc.get(db, "nonexistent-id")
        assert result is None


class TestConnectionListByProject:
    @pytest.mark.asyncio
    async def test_list_returns_project_connections(self, db):
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        await svc.create(db, project_id=p1.id, name="C1", db_type="pg", db_port=5432, db_name="db1")
        await svc.create(
            db, project_id=p1.id, name="C2", db_type="mysql", db_port=3306, db_name="db2"
        )
        await svc.create(db, project_id=p2.id, name="C3", db_type="pg", db_port=5432, db_name="db3")

        conns = await svc.list_by_project(db, p1.id)
        assert len(conns) == 2
        names = {c.name for c in conns}
        assert names == {"C1", "C2"}

    @pytest.mark.asyncio
    async def test_list_empty_project(self, db):
        proj = await _make_project(db)
        conns = await svc.list_by_project(db, proj.id)
        assert conns == []


class TestConnectionUpdate:
    @pytest.mark.asyncio
    async def test_update_fields(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="Original", db_type="pg", db_port=5432, db_name="db"
        )
        updated = await svc.update(db, conn.id, name="Renamed", db_port=5433)
        assert updated is not None
        assert updated.name == "Renamed"

    @pytest.mark.asyncio
    async def test_update_password(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="PW", db_type="pg", db_port=5432, db_name="db"
        )
        assert conn.db_password_encrypted is None
        updated = await svc.update(db, conn.id, db_password="newpass")
        assert updated is not None
        assert updated.db_password_encrypted is not None

    @pytest.mark.asyncio
    async def test_update_clears_password_with_none(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="ClearPW",
            db_type="pg",
            db_port=5432,
            db_name="db",
            db_password="secret",
        )
        assert conn.db_password_encrypted is not None
        updated = await svc.update(db, conn.id, db_password=None)
        assert updated is not None
        assert updated.db_password_encrypted is None

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, db):
        result = await svc.update(db, "no-such-id", name="Foo")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_ignores_non_updatable_fields(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="NoChange", db_type="pg", db_port=5432, db_name="db"
        )
        original_id = conn.id
        updated = await svc.update(db, conn.id, id="hacked-id")
        assert updated is not None
        assert updated.id == original_id


class TestConnectionDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="Del", db_type="pg", db_port=5432, db_name="db"
        )
        result = await svc.delete(db, conn.id)
        assert result is True
        assert await svc.get(db, conn.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        result = await svc.delete(db, "no-such-id")
        assert result is False


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_not_found(self, db):
        result = await svc.test_connection(db, "nonexistent")
        assert result == {"success": False, "error": "Connection not found"}

    @pytest.mark.asyncio
    @patch("app.services.connection_service.get_connector")
    @patch.object(ConnectionService, "to_config")
    async def test_successful_connection(self, mock_to_config, mock_get_connector, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="Test", db_type="pg", db_port=5432, db_name="db"
        )

        mock_config = MagicMock()
        mock_config.ssh_exec_mode = False
        mock_to_config.return_value = mock_config

        mock_connector = AsyncMock()
        mock_connector.test_connection.return_value = True
        mock_get_connector.return_value = mock_connector

        result = await svc.test_connection(db, conn.id)
        assert result == {"success": True}
        mock_connector.connect.assert_awaited_once()
        mock_connector.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.connection_service.get_connector")
    @patch.object(ConnectionService, "to_config")
    async def test_failed_test_query(self, mock_to_config, mock_get_connector, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="Fail", db_type="pg", db_port=5432, db_name="db"
        )

        mock_config = MagicMock()
        mock_config.ssh_exec_mode = False
        mock_to_config.return_value = mock_config

        mock_connector = AsyncMock()
        mock_connector.test_connection.return_value = False
        mock_get_connector.return_value = mock_connector

        result = await svc.test_connection(db, conn.id)
        assert result["success"] is False
        assert "test query failed" in result["error"]

    @pytest.mark.asyncio
    @patch("app.services.connection_service.get_connector")
    @patch.object(ConnectionService, "to_config")
    async def test_connection_exception(self, mock_to_config, mock_get_connector, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db, project_id=proj.id, name="Err", db_type="pg", db_port=5432, db_name="db"
        )

        mock_config = MagicMock()
        mock_config.ssh_exec_mode = False
        mock_to_config.return_value = mock_config

        mock_connector = AsyncMock()
        mock_connector.connect.side_effect = ConnectionError("refused")
        mock_get_connector.return_value = mock_connector

        result = await svc.test_connection(db, conn.id)
        assert result["success"] is False
        assert "refused" in result["error"]


class TestToConfig:
    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    async def test_to_config_basic(self, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="Config",
            db_type="postgresql",
            db_host="db.host",
            db_port=5432,
            db_name="mydb",
            db_user="admin",
            db_password="secret",
        )

        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)

        config = await svc.to_config(db, conn)
        assert config.db_type == "postgresql"
        assert config.db_host == "db.host"
        assert config.db_password == "secret"

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    async def test_to_config_with_ssh_key(self, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH Config",
            db_type="postgresql",
            db_port=5432,
            db_name="mydb",
            ssh_host="bastion.host",
            ssh_key_id="key-123",
        )

        mock_ssh_svc.get_decrypted = AsyncMock(
            return_value=("-----BEGIN RSA-----\nfake\n-----END RSA-----", "passphrase")
        )

        config = await svc.to_config(db, conn)
        assert config.ssh_host == "bastion.host"
        assert config.ssh_key_content is not None
        assert config.ssh_key_passphrase == "passphrase"

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    async def test_to_config_mcp_source(self, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP Config",
            db_type="mcp",
            db_port=0,
            db_name="",
            source_type="mcp",
            mcp_server_command="node",
            mcp_server_args=["server.js"],
            mcp_transport_type="stdio",
            mcp_env={"TOKEN": "abc"},
        )

        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)

        config = await svc.to_config(db, conn)
        assert config.extra["mcp_transport_type"] == "stdio"
        assert config.extra["mcp_server_command"] == "node"
        assert config.extra["mcp_server_args"] == ["server.js"]
        assert config.extra["mcp_env"] == {"TOKEN": "abc"}

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("app.services.connection_service.decrypt", side_effect=Exception("bad key"))
    async def test_to_config_decrypt_failure(self, _mock_decrypt, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="BadCrypto",
            db_type="pg",
            db_port=5432,
            db_name="db",
            db_password="secret",
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="Cannot decrypt credentials"):
            await svc.to_config(db, conn)

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    async def test_to_config_invalid_ssh_pre_commands_json(self, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="BadJSON",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        conn.ssh_pre_commands = "NOT-JSON"
        await db.commit()
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)
        config = await svc.to_config(db, conn)
        assert config.ssh_pre_commands is None

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    async def test_to_config_invalid_mcp_server_args_json(self, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="BadMCP",
            db_type="mcp",
            db_port=0,
            db_name="",
            source_type="mcp",
        )
        conn.mcp_server_args = "NOT-JSON"
        await db.commit()
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)
        config = await svc.to_config(db, conn)
        assert config.extra["mcp_server_args"] == []

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("app.services.connection_service.decrypt")
    async def test_to_config_mcp_env_decrypt_failure(self, mock_decrypt, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCPEnvFail",
            db_type="mcp",
            db_port=0,
            db_name="",
            source_type="mcp",
            mcp_env={"KEY": "val"},
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)
        original_decrypt = decrypt

        def selective_decrypt(value):
            if value == conn.mcp_env_encrypted:
                raise Exception("bad key")
            return original_decrypt(value)

        mock_decrypt.side_effect = selective_decrypt
        config = await svc.to_config(db, conn)
        assert config.extra["mcp_env"] == {}


class TestUpdateExtended:
    @pytest.mark.asyncio
    async def test_update_connection_string(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="ConnStr",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        updated = await svc.update(db, conn.id, connection_string="postgresql://host/db")
        assert updated is not None
        assert updated.connection_string_encrypted is not None

    @pytest.mark.asyncio
    async def test_update_clears_connection_string(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="ConnStr",
            db_type="pg",
            db_port=5432,
            db_name="db",
            connection_string="postgresql://host/db",
        )
        assert conn.connection_string_encrypted is not None
        updated = await svc.update(db, conn.id, connection_string=None)
        assert updated is not None
        assert updated.connection_string_encrypted is None

    @pytest.mark.asyncio
    async def test_update_ssh_pre_commands_list(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        updated = await svc.update(db, conn.id, ssh_pre_commands=["cmd1", "cmd2"])
        assert updated is not None
        assert updated.ssh_pre_commands == json.dumps(["cmd1", "cmd2"])

    @pytest.mark.asyncio
    async def test_update_mcp_env(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP",
            db_type="mcp",
            db_port=0,
            db_name="",
        )
        updated = await svc.update(db, conn.id, mcp_env={"SECRET": "value"})
        assert updated is not None
        assert updated.mcp_env_encrypted is not None

    @pytest.mark.asyncio
    async def test_update_clears_mcp_env(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP",
            db_type="mcp",
            db_port=0,
            db_name="",
            mcp_env={"SECRET": "value"},
        )
        updated = await svc.update(db, conn.id, mcp_env=None)
        assert updated is not None
        assert updated.mcp_env_encrypted is None

    @pytest.mark.asyncio
    async def test_update_mcp_server_args_list(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="MCP",
            db_type="mcp",
            db_port=0,
            db_name="",
        )
        updated = await svc.update(db, conn.id, mcp_server_args=["--flag", "val"])
        assert updated is not None
        assert updated.mcp_server_args == json.dumps(["--flag", "val"])

    @pytest.mark.asyncio
    async def test_update_sanitizes_strings(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="Clean",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        updated = await svc.update(db, conn.id, name="  Spaced  ", ssh_host="  host.com\t")
        assert updated is not None
        assert updated.name == "Spaced"
        assert updated.ssh_host == "host.com"


class TestListByProjectPagination:
    @pytest.mark.asyncio
    async def test_skip_and_limit(self, db):
        proj = await _make_project(db)
        for i in range(5):
            await svc.create(
                db,
                project_id=proj.id,
                name=f"C{i}",
                db_type="pg",
                db_port=5432,
                db_name="db",
            )
        page = await svc.list_by_project(db, proj.id, skip=2, limit=2)
        assert len(page) == 2

    @pytest.mark.asyncio
    async def test_skip_beyond_total(self, db):
        proj = await _make_project(db)
        await svc.create(
            db,
            project_id=proj.id,
            name="Only",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        page = await svc.list_by_project(db, proj.id, skip=100)
        assert page == []


class TestTestSsh:
    @pytest.mark.asyncio
    async def test_ssh_not_found(self, db):
        result = await svc.test_ssh(db, "nonexistent")
        assert result == {"success": False, "error": "Connection not found"}

    @pytest.mark.asyncio
    async def test_ssh_no_host(self, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="NoSSH",
            db_type="pg",
            db_port=5432,
            db_name="db",
        )
        result = await svc.test_ssh(db, conn.id)
        assert result == {"success": False, "error": "No SSH host configured"}

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("asyncssh.connect")
    async def test_ssh_success(self, mock_connect, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH OK",
            db_type="pg",
            db_port=5432,
            db_name="db",
            ssh_host="bastion.example.com",
            ssh_user="deploy",
            ssh_port=22,
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)

        mock_run_result = MagicMock()
        mock_run_result.stdout = "__SSH_TEST_OK__\nmy-server"
        mock_run_result.exit_status = 0

        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.run = AsyncMock(return_value=mock_run_result)
        mock_ssh_conn.__aenter__ = AsyncMock(return_value=mock_ssh_conn)
        mock_ssh_conn.__aexit__ = AsyncMock(return_value=False)
        mock_connect.return_value = mock_ssh_conn

        result = await svc.test_ssh(db, conn.id)
        assert result["success"] is True
        assert result["hostname"] == "my-server"

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("asyncssh.connect")
    async def test_ssh_marker_not_found(self, mock_connect, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH Bad",
            db_type="pg",
            db_port=5432,
            db_name="db",
            ssh_host="bastion.example.com",
            ssh_user="deploy",
            ssh_port=22,
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)

        mock_run_result = MagicMock()
        mock_run_result.stdout = "unexpected output"
        mock_run_result.exit_status = 1

        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.run = AsyncMock(return_value=mock_run_result)
        mock_ssh_conn.__aenter__ = AsyncMock(return_value=mock_ssh_conn)
        mock_ssh_conn.__aexit__ = AsyncMock(return_value=False)
        mock_connect.return_value = mock_ssh_conn

        result = await svc.test_ssh(db, conn.id)
        assert result["success"] is False
        assert "stdout" in result

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("asyncssh.connect", side_effect=Exception("Connection refused"))
    async def test_ssh_connection_exception(self, _mock_connect, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH Err",
            db_type="pg",
            db_port=5432,
            db_name="db",
            ssh_host="bastion.example.com",
            ssh_user="deploy",
            ssh_port=22,
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=None)

        result = await svc.test_ssh(db, conn.id)
        assert result["success"] is False
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    @patch("app.services.connection_service._ssh_key_svc")
    @patch("asyncssh.connect")
    @patch("asyncssh.import_private_key")
    async def test_ssh_with_key(self, mock_import_key, mock_connect, mock_ssh_svc, db):
        proj = await _make_project(db)
        conn = await svc.create(
            db,
            project_id=proj.id,
            name="SSH Key",
            db_type="pg",
            db_port=5432,
            db_name="db",
            ssh_host="bastion.example.com",
            ssh_user="deploy",
            ssh_port=22,
            ssh_key_id="key-1",
        )
        mock_ssh_svc.get_decrypted = AsyncMock(return_value=("---KEY---", "pass"))
        mock_import_key.return_value = MagicMock()

        mock_run_result = MagicMock()
        mock_run_result.stdout = "__SSH_TEST_OK__\nhost1"
        mock_run_result.exit_status = 0

        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.run = AsyncMock(return_value=mock_run_result)
        mock_ssh_conn.__aenter__ = AsyncMock(return_value=mock_ssh_conn)
        mock_ssh_conn.__aexit__ = AsyncMock(return_value=False)
        mock_connect.return_value = mock_ssh_conn

        result = await svc.test_ssh(db, conn.id)
        assert result["success"] is True
        mock_import_key.assert_called_once_with("---KEY---", "pass")
