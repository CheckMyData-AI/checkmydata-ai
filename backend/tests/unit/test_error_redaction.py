"""F-CONN-08 — a secret must not ride out on an error string.

What was measured, and what was not:

* **Verified:** the connectors return `QueryResult(error=str(e))` unredacted
  (`postgres.py`, `mysql.py`, `clickhouse.py`, `mongodb.py`, `ssh_exec.py`), that
  text reaches the API response, and the same text is logged. The SSH exec path
  substitutes `db_password` into a command template (`ssh_exec.py:_config_vars`),
  so a secret is present in that layer by construction.
* **Not verified:** that a specific driver exception embeds it. A real asyncpg
  failure does not — `postgresql://admin:SuperSecret123@host/db` produces
  `[Errno 8] nodename nor servname provided, or not known`, with no password in
  it. The leak needs something to WRAP the error with the DSN or the command.

So this is defence in depth rather than a demonstrated exfiltration, and it is
worth having for one reason: the redaction already existed and was wired only to
Sentry egress (F-LLM-03), which is the one path a secret does not need to take to
do damage. The API response and the application log are the other two.
"""

from __future__ import annotations

import pytest

from app.core.redaction import scrub_text


class TestUrlCredentials:
    def test_a_dsn_password_is_redacted(self):
        out = scrub_text("could not connect using postgresql://admin:SuperSecret123@db:5432/app")
        assert "SuperSecret123" not in out
        # The useful half survives — a redaction that eats the host tells an
        # operator nothing about what failed.
        assert "db:5432" in out
        assert "admin" in out

    def test_a_url_without_credentials_is_untouched(self):
        raw = "could not connect using postgresql://db:5432/app"
        assert scrub_text(raw) == raw


class TestKeyValueSecrets:
    @pytest.mark.parametrize(
        "raw",
        [
            "clickhouse-client --password=SuperSecret123 --query 'SELECT 1'",
            "auth failed: token=abcdef1234567890",
            "headers: {'Authorization': 'Bearer abcdef1234567890'}",
            "api_key: abcdef1234567890",
        ],
    )
    def test_secret_shapes_are_redacted(self, raw: str):
        out = scrub_text(raw)
        assert "SuperSecret123" not in out
        assert "abcdef1234567890" not in out

    def test_an_ordinary_message_is_returned_unchanged(self):
        raw = "relation \"users\" does not exist"
        assert scrub_text(raw) == raw


class TestConnectorSites:
    """Every path that hands an error to a caller must go through the scrub."""

    def test_no_connector_returns_a_raw_exception_string(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []
        for path in sorted((root / "connectors").glob("*.py")):
            for i, line in enumerate(path.read_text().split("\n"), 1):
                # `error=str(e)` hands the driver's own text straight out.
                if re.search(r"error=str\((?:e|exc)\)", line):
                    offenders.append(f"connectors/{path.name}:{i}")
        assert offenders == [], (
            "these sites return an unredacted exception string to the caller: " f"{offenders}"
        )

    def test_the_sentry_hook_still_uses_the_same_patterns(self):
        """One pattern set, not two — a second copy is one that drifts."""
        from app.core import sentry

        assert sentry.scrub_text is scrub_text
