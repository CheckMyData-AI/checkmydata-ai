"""C-06: the server reads a connection string the way the form that wrote it does.

`urlparse` leaves the userinfo percent-encoded, and the connection form decodes it — so
a password with `@`, `/` or `:` in it worked in the browser's preview and failed at the
server with an authentication error naming nothing. A DSN with no user became a login as
`root` on MySQL and `default` on ClickHouse: a successful login as somebody else, where
a refusal was the honest answer.
"""

from __future__ import annotations

import pytest

from app.connectors.dsn import DsnError, parse_dsn


def test_the_userinfo_is_decoded():
    parsed = parse_dsn("mysql://alice%40corp:p%40ss%2Fword@db.example.com:3307/shop")

    assert parsed.user == "alice@corp"
    assert parsed.password == "p@ss/word"
    assert (parsed.host, parsed.port, parsed.database) == ("db.example.com", 3307, "shop")


def test_the_form_and_the_server_now_agree():
    # The same string the TypeScript parser decodes (connection-string.ts): both sides
    # must produce one account, or a connection that "tested fine" fails on first use.
    parsed = parse_dsn("postgresql://u%2Bx:pw%3A1@10.0.0.5/db", default_port=5432)

    assert (parsed.user, parsed.password, parsed.port) == ("u+x", "pw:1", 5432)


def test_a_string_with_no_user_is_refused():
    with pytest.raises(DsnError, match="no user"):
        parse_dsn("mysql://db.example.com:3306/shop")


def test_a_string_with_no_host_is_refused():
    with pytest.raises(DsnError, match="no host"):
        parse_dsn("mysql:///shop")


def test_neither_engine_invents_an_account():
    """Structural: the defaults that made a user-less DSN succeed are gone."""
    from pathlib import Path

    connectors = Path(__file__).resolve().parents[3] / "app" / "connectors"
    mysql = (connectors / "mysql.py").read_text(encoding="utf-8")
    clickhouse = (connectors / "clickhouse.py").read_text(encoding="utf-8")

    assert 'parsed.username or "root"' not in mysql
    assert 'parsed.username or config.db_user or "default"' not in clickhouse
    assert "parse_dsn(" in mysql and "parse_dsn(" in clickhouse
