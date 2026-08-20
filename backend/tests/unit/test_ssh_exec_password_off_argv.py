"""F-SSH-02 — the database password rode in the remote command line.

`asyncssh`'s `conn.run(command)` sends an SSH *exec* request, and sshd runs it through the
login shell as `sh -c "<command>"`. Whatever is in that string is in that process's argv,
readable by **any** user on the remote host through `ps` or `/proc/<pid>/cmdline` for as
long as the query takes.

Every template put it there — `PGPASSWORD="…"`, `MYSQL_PWD="…"`, `CLICKHOUSE_PASSWORD="…"`.
The board recorded this as a ClickHouse problem; it was all three.

**And the ClickHouse template did not even work.** A command prefix assignment sets the
variable for the command's own environment, so `"$VAR"` on the same line is expanded by
the *calling* shell, from the value it already had:

    $ sh -c 'FOO="secret" printf "argv:[%s]\\n" "$FOO"'
    argv:[]
    $ FOO=leaked sh -c 'FOO="secret" printf "argv:[%s]\\n" "$FOO"'
    argv:[leaked]

So `--password "$CLICKHOUSE_PASSWORD"` passed an empty string — or, if the login shell
happened to export that name, somebody else's value. `--password` is gone; the client
reads `CLICKHOUSE_PASSWORD` from the environment, which is what setting it was for.

The password now travels on the channel's **stdin**, and the command carries only
`IFS= read -r DBPASS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.exec_templates import EXEC_TEMPLATES
from app.connectors.ssh_exec import SSHExecConnector

SECRET = "hunter2-do-not-leak"


@dataclass
class FakeSSHResult:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0


def make_config(**overrides) -> ConnectionConfig:
    defaults = dict(
        db_type="mysql",
        db_host="10.0.0.9",
        db_port=3306,
        db_name="testdb",
        db_user="testuser",
        db_password=SECRET,
        ssh_host="10.0.0.1",
        ssh_user="deploy",
        ssh_key_content="fake-key",
        ssh_exec_mode=True,
    )
    defaults.update(overrides)
    return ConnectionConfig(**defaults)


def _connector(**overrides) -> SSHExecConnector:
    c = SSHExecConnector()
    c._config = make_config(**overrides)
    return c


class TestTheSecretIsNotInTheCommandString:
    """The command string becomes `sh -c "<it>"` on the remote host. Nothing in it is
    private."""

    @pytest.mark.parametrize("db_type", ["mysql", "postgres", "clickhouse"])
    @pytest.mark.parametrize("kind", ["query", "test", "introspect_tables"])
    def test_no_template_puts_the_password_in_argv(self, db_type, kind):
        command, _ = _connector(db_type=db_type)._build_command(kind, "SELECT 1")

        assert SECRET not in command, f"{db_type}/{kind} still leaks the password to ps"

    @pytest.mark.parametrize("db_type", ["mysql", "postgres", "clickhouse"])
    def test_the_command_reads_the_password_from_stdin(self, db_type):
        command, stdin = _connector(db_type=db_type)._build_command("query", "SELECT 1")

        assert "read -r DBPASS" in command
        assert stdin == SECRET + "\n"

    @pytest.mark.parametrize("db_type", ["mysql", "postgres", "clickhouse"])
    def test_the_client_still_receives_it_through_the_environment(self, db_type):
        command, _ = _connector(db_type=db_type)._build_command("query", "SELECT 1")

        assert "$DBPASS" in command, "the client would authenticate with nothing"


class TestTheClickHouseTemplateWasAlsoBroken:
    def test_password_is_no_longer_passed_as_an_argument(self):
        """`--password "$CLICKHOUSE_PASSWORD"` expanded in the calling shell, so the
        client got an empty string — and putting the real value there instead would have
        landed it in `ps` output, which is the finding."""
        for kind, template in EXEC_TEMPLATES["clickhouse"].items():
            assert "--password" not in template, f"clickhouse/{kind} still passes --password"

    def test_the_environment_variable_is_still_set(self):
        for kind, template in EXEC_TEMPLATES["clickhouse"].items():
            assert "CLICKHOUSE_PASSWORD=" in template, f"clickhouse/{kind} sets no password"


class TestNoTemplateStillInterpolatesTheSecret:
    """A template with `{db_password}` in it is the whole bug, so none may have one."""

    def test_no_builtin_template_references_db_password(self):
        offenders = [
            f"{db_type}/{kind}"
            for db_type, kinds in EXEC_TEMPLATES.items()
            for kind, template in kinds.items()
            if "{db_password}" in template
        ]

        assert not offenders, f"these interpolate the password into argv: {offenders}"


class TestTheQueryStillGetsThrough:
    """The password takes the first line of the channel's stdin and the query is piped in
    after it. If that ordering were wrong the client would try to run the password."""

    def test_the_query_is_still_piped_to_the_client(self):
        command, _ = _connector()._build_command("query", "SELECT 42")

        assert "SELECT 42" in command
        assert "|" in command
        assert command.index("read -r DBPASS") < command.index("SELECT 42")

    def test_pre_commands_still_run_first(self):
        command, _ = _connector(
            ssh_pre_commands=["export PATH=/usr/local/bin:$PATH"]
        )._build_command("query", "SELECT 1")

        assert command.startswith("export PATH=/usr/local/bin:$PATH && ")


class TestACustomTemplateKeepsWorking:
    """A user's own template is theirs. It keeps the old substitution — with a warning,
    because it is the same exposure — rather than silently breaking their connection."""

    def test_a_custom_template_with_the_placeholder_still_substitutes(self, caplog):
        command, stdin = _connector(
            ssh_command_template="custom-cli -p {db_password} -d {db_name}"
        )._build_command("query", "SELECT 1")

        assert SECRET in command
        assert stdin is None, "no reader in the command, so nothing may be sent to it"
        assert any("command line" in r.message for r in caplog.records)

    def test_a_custom_template_without_the_placeholder_gets_the_secret_on_stdin(self):
        command, stdin = _connector(
            ssh_command_template='MYPASS="$DBPASS" custom-cli -d {db_name}'
        )._build_command("query", "SELECT 1")

        assert SECRET not in command
        assert stdin == SECRET + "\n"


class TestAPasswordWithANewlineIsRefusedRatherThanTruncated:
    def test_it_raises(self):
        """`read -r` stops at the first newline. Silently truncating would authenticate
        with half a password and report whatever the server says about that."""
        with pytest.raises(ValueError, match="newline"):
            _connector(db_password="two\nlines")._build_command("query", "SELECT 1")


class TestTheSecretActuallyReachesTheChannel:
    """The build is only half of it — `_run_command` has to send the payload, or the
    remote `read` gets EOF and the client authenticates with an empty string."""

    @pytest.mark.asyncio
    @patch("app.connectors.ssh_exec.connect_with_policy", new_callable=AsyncMock)
    @patch("app.connectors.ssh_exec.asyncssh")
    async def test_run_command_sends_the_password_as_input(self, _asyncssh, mock_connect):
        conn = MagicMock()
        conn.run = AsyncMock(return_value=FakeSSHResult(stdout="ok"))
        mock_connect.return_value = conn

        connector = _connector()
        await connector.connect(connector._config)
        await connector.execute_query("SELECT 1")

        _, kwargs = conn.run.call_args
        assert kwargs.get("input") == SECRET + "\n"
        assert SECRET not in conn.run.call_args[0][0]
