"""F-SSH-07: a reconnect re-runs the command, which can execute it twice.

`_run_command` catches a lost connection, reconnects, and then runs the *same*
command again. If the first attempt reached the server and executed before the
connection dropped, the command runs twice — and this path serves note execution,
batch `/execute` and the agent's `execute_query`, so on a connection that is not
read-only that can be an `UPDATE` applied twice.

`asyncssh.ConnectionLost` cannot say whether the command reached the server, so the
retry decision is not the connector's to guess. The caller states it: `idempotent`
defaults to **False**, and the only automatic answer is "this statement is read-only,
therefore repeating it changes nothing".
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import asyncssh
import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_exec import SSHExecConnector


@dataclass
class FakeResult:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0


def _config(**over) -> ConnectionConfig:
    base = dict(
        db_type="postgres",
        db_host="127.0.0.1",
        db_port=5432,
        db_name="testdb",
        db_user="testuser",
        db_password="pw",
        ssh_host="10.0.0.1",
        ssh_port=22,
        ssh_user="deploy",
        ssh_key_content="k",
        ssh_exec_mode=True,
    )
    base.update(over)
    return ConnectionConfig(**base)


#: The reconnect path sends a liveness probe of its own, so counting `run` calls
#: does not answer the question. What matters is whether the *original command* was
#: sent twice, so every send is recorded by text and the probe is excluded.
_PROBE = "__SSH_EXEC_ALIVE__"


def _connector(*, drops: int = 1) -> tuple[SSHExecConnector, dict]:
    """A connector whose first `drops` real sends raise ConnectionLost, then succeed."""
    calls: dict = {"sent": [], "reconnect": 0}
    conn = MagicMock()

    async def run(command, **kw):  # noqa: ARG001
        if _PROBE in command:
            return FakeResult(stdout=_PROBE)
        calls["sent"].append(command)
        if len(calls["sent"]) <= drops:
            raise asyncssh.ConnectionLost("dropped")
        return FakeResult(stdout="ok")

    conn.run = AsyncMock(side_effect=run)
    c = SSHExecConnector()
    c._conn = conn
    c._config = _config()

    async def fake_connect(cfg):  # noqa: ARG001
        calls["reconnect"] += 1
        c._conn = conn

    c.connect = AsyncMock(side_effect=fake_connect)  # type: ignore[method-assign]
    return c, calls


class TestRetryNeedsPermission:
    @pytest.mark.asyncio
    async def test_a_command_not_declared_idempotent_is_not_retried(self):
        c, calls = _connector()
        with pytest.raises(RuntimeError) as exc:
            await c._run_command("psql -c 'UPDATE t SET x=1'")
        # The point is not that it failed — it is that the caller is told the outcome
        # is unknown, rather than the command being silently applied twice.
        msg = str(exc.value).lower()
        assert "may already have" in msg or "unknown" in msg, exc.value
        assert len(calls["sent"]) == 1, f"the command was re-sent: {calls['sent']}"

    @pytest.mark.asyncio
    async def test_an_idempotent_command_is_retried_after_reconnect(self):
        c, calls = _connector()
        out, _, code = await c._run_command("psql -c 'SELECT 1'", idempotent=True)
        assert out == "ok" and code == 0
        assert len(calls["sent"]) == 2, calls["sent"]

    @pytest.mark.asyncio
    async def test_only_one_retry_is_attempted(self):
        """A second drop must surface, not loop."""
        c, _ = _connector(drops=2)
        with pytest.raises(Exception):  # noqa: B017 - any surfaced failure is correct
            await c._run_command("psql -c 'SELECT 1'", idempotent=True)

    @pytest.mark.asyncio
    async def test_the_default_is_fail_closed(self):
        import inspect

        sig = inspect.signature(SSHExecConnector._run_command)
        assert sig.parameters["idempotent"].default is False


class TestQueryPathDecidesFromTheStatement:
    @pytest.mark.asyncio
    async def test_a_select_is_retried(self):
        c, calls = _connector()
        c._config = _config(is_read_only=False)
        await c.execute_query("SELECT 1")
        assert len(calls["sent"]) == 2, "a read-only statement is safe to repeat"

    @pytest.mark.asyncio
    async def test_an_update_on_a_writable_connection_is_not_retried(self):
        c, calls = _connector()
        c._config = _config(is_read_only=False)
        result = await c.execute_query("UPDATE t SET x = 1")
        assert len(calls["sent"]) == 1, "a mutating statement must not be re-sent"
        assert result.error, "and the caller must be told, not handed a silent success"

    @pytest.mark.asyncio
    async def test_a_read_only_connection_makes_anything_repeatable(self):
        """The DB session itself refuses writes, so nothing it runs can mutate."""
        c, calls = _connector()
        c._config = _config(is_read_only=True)
        await c.execute_query("UPDATE t SET x = 1")
        assert len(calls["sent"]) == 2

    @pytest.mark.asyncio
    async def test_a_comment_cannot_disguise_a_mutation(self):
        c, calls = _connector()
        c._config = _config(is_read_only=False)
        await c.execute_query("/* SELECT */ DELETE FROM t")
        assert len(calls["sent"]) == 1, "comment stripping must happen before the decision"

    @pytest.mark.asyncio
    async def test_a_second_statement_cannot_ride_along(self):
        c, calls = _connector()
        c._config = _config(is_read_only=False)
        await c.execute_query("SELECT 1; DROP TABLE t")
        assert len(calls["sent"]) == 1, "multi-statement is not a repeatable read"


class TestIntrospectionDeclaresItself:
    def test_every_introspection_call_site_declares_idempotence(self):
        """Fixed read-only introspection commands are safe to repeat, and each says so.

        Asserted on the syntax tree: a site that forgets gets the fail-closed default,
        which is safe but turns a transient drop into a schema-refresh failure. The
        query path is excluded because it must *compute* the answer, not assert it.
        """
        import ast
        import inspect

        from app.connectors import ssh_exec as mod

        tree = ast.parse(inspect.getsource(mod))
        enclosing: dict[int, str] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for n in ast.walk(fn):
                    enclosing.setdefault(id(n), fn.name)

        missing = []
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr != "_run_command":
                continue
            owner = enclosing.get(id(n), "?")
            if owner in {"execute_query", "_run_command"}:
                continue
            if not any(kw.arg == "idempotent" for kw in n.keywords):
                missing.append(f"{owner}() line {n.lineno}")
        assert not missing, f"call sites with no idempotence declaration: {missing}"
