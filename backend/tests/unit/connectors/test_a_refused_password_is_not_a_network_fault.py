"""T05b — the PRJ-08 residue on the path production uses (MySQL through an SSH tunnel).

Audit 2026-09-23 §3.2 (`docs/audits/2026-09-23-recent-work-audit.md`):

* F-C3 — `pymysql.err.OperationalError` is also what MySQL raises for error 1045
  *Access denied*. C-05 put the whole class in `TRANSIENT_CONNECT_ERRORS`, so a wrong
  password was retried three times, and through a tunnel `open_through` force-closed the
  SHARED tunnel under every other connection's live pool, then reported the failure as
  "via SSH tunnel". A refusal is an answer, not a fault; asking again cannot change it.
* F-C4 — the idle sweep closed a tunnel 30 minutes after its last query while the SQL
  agent's cached connector still held a pool through it (C-03 made queries count as
  activity; the health probe's `SELECT 1` does not). The next chat question failed until
  the health loop's `reconnect()` ran, up to `health_check_interval_seconds` later. The
  cache now notices the tunnel is gone and reconnects before the question. (Keeping
  referenced tunnels out of the sweep was rejected: a reference is released only when a
  connection is DELETED, not on `disconnect()`, so it would have kept every tunnel ever
  opened alive for the life of the process.)
"""

from __future__ import annotations

import pymysql.err
import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_tunnel import SSHTunnelManager
from app.connectors.transient_errors import is_transient_connect_error
from app.core.retry import retry


def _config(**over):
    base = dict(
        db_type="mysql",
        db_host="10.0.0.5",
        db_port=3306,
        db_name="db",
        db_user="u",
        ssh_host="bastion.example.com",
        ssh_port=22,
        ssh_user="deploy",
        connection_id="conn-1",
    )
    base.update(over)
    return ConnectionConfig(**base)


@pytest.mark.parametrize("code", [1044, 1045, 1049, 1130, 1251, 1698])
def test_a_refusal_by_the_server_is_not_transient(code: int) -> None:
    assert is_transient_connect_error(pymysql.err.OperationalError(code, "refused")) is False


@pytest.mark.parametrize("code", [2002, 2003, 2006, 2013])
def test_a_lost_or_unreachable_server_still_is(code: int) -> None:
    assert is_transient_connect_error(pymysql.err.OperationalError(code, "gone")) is True


def test_the_builtin_network_errors_still_are() -> None:
    assert is_transient_connect_error(ConnectionRefusedError()) is True
    assert is_transient_connect_error(TimeoutError()) is True
    assert is_transient_connect_error(ValueError("not a network error")) is False


class _Manager(SSHTunnelManager):
    def __init__(self) -> None:
        super().__init__()
        self.closed = 0

    async def get_or_create(self, config):
        return "127.0.0.1", 54321

    async def close_for_config(self, config, *, force: bool = False) -> bool:
        self.closed += 1
        return True


@pytest.mark.asyncio
async def test_a_wrong_password_does_not_tear_down_the_shared_tunnel() -> None:
    mgr = _Manager()
    attempts = 0

    async def opener(host: str, port: int):
        nonlocal attempts
        attempts += 1
        raise pymysql.err.OperationalError(1045, "Access denied for user 'u'@'10.0.0.9'")

    with pytest.raises(pymysql.err.OperationalError) as excinfo:
        await mgr.open_through(_config(), opener)

    assert attempts == 1, "a refused password was asked again"
    assert mgr.closed == 0, "the shared tunnel was closed under everyone else's pool"
    assert "via SSH tunnel" not in str(excinfo.value), "the bastion is not the problem"


@pytest.mark.asyncio
async def test_the_direct_retry_does_not_repeat_a_refusal() -> None:
    calls = 0

    @retry(max_attempts=3, backoff_seconds=0, retry_if=is_transient_connect_error)
    async def connect():
        nonlocal calls
        calls += 1
        raise pymysql.err.OperationalError(1045, "Access denied")

    with pytest.raises(pymysql.err.OperationalError):
        await connect()
    assert calls == 1


class _Cached:
    """A cached connector whose pool points at a tunnel that may be gone."""

    def __init__(self, can_reconnect: bool = True) -> None:
        self.can_reconnect = can_reconnect
        self.reconnected = 0
        self.rebuilt = 0

    async def reconnect(self) -> bool:
        self.reconnected += 1
        return self.can_reconnect

    async def disconnect(self) -> None:
        pass

    async def connect(self, cfg) -> None:
        self.rebuilt += 1


@pytest.mark.asyncio
async def test_a_cached_connector_whose_tunnel_was_swept_reconnects_before_the_question(
    monkeypatch,
) -> None:
    from app.agents import sql_agent
    from app.connectors import ssh_tunnel

    mgr = SSHTunnelManager()
    monkeypatch.setattr(ssh_tunnel, "shared_tunnel_manager", mgr)
    config = _config()

    assert sql_agent._tunnel_was_swept(config) is True, "no tunnel is held for this config"
    conn = _Cached()
    await sql_agent.SQLAgent._rebuild_swept(conn, config)
    assert conn.reconnected == 1 and conn.rebuilt == 0

    stubborn = _Cached(can_reconnect=False)
    await sql_agent.SQLAgent._rebuild_swept(stubborn, config)
    assert stubborn.rebuilt == 1, "an adapter without reconnect() is rebuilt from scratch"


@pytest.mark.asyncio
async def test_a_live_tunnel_and_an_exec_session_are_left_alone(monkeypatch) -> None:
    from app.agents import sql_agent
    from app.connectors import ssh_tunnel

    mgr = SSHTunnelManager()
    monkeypatch.setattr(ssh_tunnel, "shared_tunnel_manager", mgr)
    config = _config()

    class _Live:
        def touch(self) -> None:
            self.touched = True

    live = _Live()
    mgr._tunnels[mgr._key(config)] = live  # type: ignore[assignment]
    assert sql_agent._tunnel_was_swept(config) is False
    assert getattr(live, "touched", False), "a question counts as activity"

    assert sql_agent._tunnel_was_swept(_config(ssh_exec_mode=True)) is False
    assert sql_agent._tunnel_was_swept(_config(ssh_host=None)) is False


# F-C7 — C-14 caught `KeyImportError`, but a WRONG PASSPHRASE on a well-formed encrypted
# key raises `asyncssh.KeyEncryptionError`, a sibling `ValueError`: it still went through
# the reconnect loop three times as a flapping bastion, and SSH-exec mode did not wrap
# key import at all. Both paths now read the key through one function.


def _encrypted_key() -> str:
    import asyncssh

    key = asyncssh.generate_private_key("ssh-ed25519")
    return key.export_private_key("openssh", passphrase="right").decode()


def test_a_wrong_passphrase_is_named_not_retried() -> None:
    from app.connectors.ssh_tunnel import SSHKeyUnusableError, load_client_key

    config = _config(ssh_key_content=_encrypted_key(), ssh_key_passphrase="wrong")
    with pytest.raises(SSHKeyUnusableError, match="passphrase"):
        load_client_key(config)


def test_the_right_passphrase_still_loads_and_no_key_is_none() -> None:
    from app.connectors.ssh_tunnel import load_client_key

    assert load_client_key(_config(ssh_key_content=_encrypted_key(), ssh_key_passphrase="right"))
    assert load_client_key(_config()) is None


def test_exec_mode_reads_the_key_through_the_same_function() -> None:
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "app" / "connectors" / "ssh_exec.py").read_text()
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
    }
    assert "import_private_key" not in calls, "exec mode imports the key unguarded"
    assert "load_client_key" in calls


# F-C2 — C-02 refused `{db_password}` in a new template, but the variable the server
# fills from stdin, `$DBPASS`, is just as visible in `ps` when a custom template hands it
# to the client as an ARGUMENT. The only safe use is an environment assignment.


@pytest.mark.parametrize(
    "template",
    [
        'mysql -p"$DBPASS" -h {db_host} {db_name}',
        "mysql --password=$DBPASS {db_name}",
        "psql 'postgres://u:${DBPASS}@{db_host}/{db_name}'",
        'clickhouse-client --password "$DBPASS"',
    ],
)
def test_a_new_template_may_not_pass_the_password_as_an_argument(template: str) -> None:
    from app.connectors.exec_templates import (
        CommandTemplateValidationError,
        validate_new_command_template,
    )

    with pytest.raises(CommandTemplateValidationError, match="environment"):
        validate_new_command_template(template)


@pytest.mark.parametrize(
    "template",
    [
        'MYSQL_PWD="$DBPASS" mysql -h {db_host} {db_name}',
        "PGPASSWORD=$DBPASS psql -h {db_host} {db_name}",
        'CLICKHOUSE_PASSWORD="${DBPASS}" clickhouse-client --host {db_host}',
        "mysql -h {db_host} {db_name}",
    ],
)
def test_an_environment_assignment_is_the_safe_shape(template: str) -> None:
    from app.connectors.exec_templates import validate_new_command_template

    assert validate_new_command_template(template) == template


# C-15 residue — the form required an SSH user, the API accepted a host alone.


def test_creating_a_tunnel_without_a_user_is_refused() -> None:
    from pydantic import ValidationError

    from app.api.routes.connections import ConnectionCreate

    base = dict(project_id="p", name="db", db_type="mysql", db_host="h", db_name="d")
    with pytest.raises(ValidationError, match="SSH user"):
        ConnectionCreate(**base, ssh_host="bastion")
    assert ConnectionCreate(**base, ssh_host="bastion", ssh_user="deploy").ssh_user == "deploy"
    assert ConnectionCreate(**base).ssh_host in (None, "")
