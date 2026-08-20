"""Verify Alembic migrations apply cleanly on an empty database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def tmp_db(tmp_path):
    db_path = tmp_path / "test_migrations.db"
    url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    yield url, async_url, db_path


def _run_alembic(async_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR), "DATABASE_URL": async_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def test_upgrade_head_creates_all_tables(tmp_db):
    url, async_url, db_path = tmp_db
    _run_alembic(async_url, "upgrade", "head")

    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    expected = {
        "alembic_version",
        "ssh_keys",
        "projects",
        "connections",
        "knowledge_docs",
        "commit_index",
        "chat_sessions",
        "chat_messages",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"
    engine.dispose()


def test_downgrade_base_removes_tables(tmp_db):
    url, async_url, db_path = tmp_db
    _run_alembic(async_url, "upgrade", "head")
    _run_alembic(async_url, "downgrade", "base")

    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert len(tables) == 0, f"Tables remaining after downgrade: {tables}"
    engine.dispose()


def _insert(conn, table: str, values: dict) -> None:
    """Insert a row, filling every NOT NULL column the schema demands.

    Built from `PRAGMA table_info` rather than a literal column list: three attempts at
    this test failed on `projects.description` and then `projects.repo_branch`, columns
    added by unrelated migrations long after the row shape being simulated. A fixture
    that hardcodes today's schema starts failing the next time somebody adds a column,
    for a reason that has nothing to do with what it tests.
    """
    from sqlalchemy import text

    required = [
        (r[1], r[2])
        for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if r[3] and r[4] is None
    ]
    row = {name: values.get(name, 0 if "INT" in typ.upper() else "") for name, typ in required}
    row.update(values)
    cols = ", ".join(row)
    binds = ", ".join(f":{c}" for c in row)
    conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({binds})"), row)


def test_legacy_demo_connections_are_pointed_at_a_real_file(tmp_db):
    """d3e4f5a6b7c8 — found by a post-deploy check, not by a test.

    Production held one connection with `db_type='sqlite'` and `db_name=':memory:'` from
    2026-06-05. Before the demo work it failed with `Unsupported adapter: sqlite`; after
    it, the new connector refuses `:memory:` at connect — a better error for the same
    empty screen. F-EXP-01's promise held for connections created after the fix and not
    for the ones created before it, which is the half of a fix a test suite cannot see.
    """
    from sqlalchemy import text

    url, async_url, _ = tmp_db
    _run_alembic(async_url, "upgrade", "c2d3e4f5a6b7")

    engine = create_engine(url)
    owner = "11111111-2222-3333-4444-555555555555"
    with engine.begin() as conn:
        _insert(conn, "projects", {"id": "p-demo", "name": "Demo Project", "owner_id": owner})
        _insert(
            conn,
            "connections",
            {
                "id": "c-demo",
                "project_id": "p-demo",
                "name": "Demo SQLite",
                "db_type": "sqlite",
                "db_name": ":memory:",
                "is_read_only": 0,
            },
        )
        # Two control rows, and the second exists because the first did not earn the
        # `db_type == "sqlite"` clause: removing that clause left this test green, since
        # no non-sqlite row happened to be named ":memory:". A mysql connection somebody
        # typed a placeholder into is odd and not impossible, and it is exactly what the
        # clause is for.
        _insert(conn, "projects", {"id": "p-odd", "name": "Odd", "owner_id": owner})
        _insert(
            conn,
            "connections",
            {
                "id": "c-odd",
                "project_id": "p-odd",
                "name": "placeholder",
                "db_type": "mysql",
                "db_name": ":memory:",
                "is_read_only": 0,
            },
        )
        _insert(conn, "projects", {"id": "p-real", "name": "Real", "owner_id": owner})
        _insert(
            conn,
            "connections",
            {
                "id": "c-real",
                "project_id": "p-real",
                "name": "prod pg",
                "db_type": "postgres",
                "db_name": "app",
                "is_read_only": 1,
            },
        )

    _run_alembic(async_url, "upgrade", "head")

    with engine.begin() as conn:
        demo = conn.execute(
            text("SELECT db_name, is_read_only FROM connections WHERE id = 'c-demo'")
        ).fetchone()
        real = conn.execute(
            text("SELECT db_name, is_read_only FROM connections WHERE id = 'c-real'")
        ).fetchone()

    assert demo[0] == f"./data/demo/demo_{owner}.db", (
        "the path must be built from the project owner, matching demo_data.demo_db_path — "
        "the file is seeded by ConnectionService.to_config on the next config build, so a "
        "path that does not match is a demo that stays empty"
    )
    assert demo[1] in (1, True), "these rows predate F-EXP-02 and were created writable"
    assert real == ("app", 1) or real == ("app", True), "a real connection was rewritten"
    with engine.begin() as conn:
        odd = conn.execute(
            text("SELECT db_name, is_read_only FROM connections WHERE id = 'c-odd'")
        ).fetchone()
    assert odd[0] == ":memory:", "a non-sqlite connection was rewritten as if it were the demo"
    assert odd[1] in (0, False), "and its privileges were changed on the way past"

    _run_alembic(async_url, "downgrade", "-1")

    with engine.begin() as conn:
        after = conn.execute(
            text("SELECT db_name, is_read_only FROM connections WHERE id = 'c-demo'")
        ).fetchone()
    assert after[0] == ":memory:"
    assert after[1] in (1, True), (
        "downgrade must not hand back write access: reverting a path rewrite is not a "
        "reason to change a privilege, and the asymmetry is the safe direction"
    )
    engine.dispose()
