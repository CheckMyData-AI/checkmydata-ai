"""Verify Alembic migrations apply cleanly on an empty database."""

import os
import subprocess
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
        ["alembic", *args],
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
