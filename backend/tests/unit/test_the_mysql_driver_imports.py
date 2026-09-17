"""The MySQL driver must import, and must say so by name when it does not.

PyMySQL 1.2.1 (2026-09-17 08:32 UTC) removed `pymysql.converters.escape_bytes_prefixed`,
which aiomysql 0.3.2 imports at module load. Unpinned, the next image build would have
resolved 1.2.2 and `import aiomysql` would have failed — every MySQL connection, the one
production customer's database, dead at the first question. It surfaced as ~900 test
collection errors on a documentation change, which is the least readable way a dependency
can announce itself. This test is the readable way.
"""

from __future__ import annotations

from importlib.metadata import version


def test_aiomysql_imports_against_the_installed_pymysql() -> None:
    try:
        import aiomysql  # noqa: F401
    except ImportError as exc:  # pragma: no cover - the failure is the message
        raise AssertionError(
            f"aiomysql {version('aiomysql')} cannot import against PyMySQL "
            f"{version('PyMySQL')}: {exc}. Every MySQL connection fails at the first "
            "question. Check the PyMySQL ceiling in pyproject.toml."
        ) from exc


def test_the_ceiling_is_still_needed() -> None:
    """A pin outliving its reason blocks security fixes for nothing.

    When aiomysql stops importing the removed name, this fails and says to lift the
    ceiling — so the constraint cannot quietly become permanent.
    """
    import inspect

    import aiomysql.connection as conn_mod

    still_imports = "escape_bytes_prefixed" in inspect.getsource(conn_mod)
    assert still_imports, (
        "aiomysql no longer imports `escape_bytes_prefixed` — lift the `PyMySQL<1.2.1` "
        "ceiling in pyproject.toml and delete this test"
    )
