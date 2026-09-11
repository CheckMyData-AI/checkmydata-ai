"""Three unlocked callers run `alembic upgrade head` at once on every deploy (DATA-10).

The migration runner has three independent callers that all fire on a restart — the `web`
dyno's start command (on the Procfile channel), the `web` lifespan (`main.py:94-102`) and
`worker.startup` (`worker.py:296`). None of them takes a lock, and only one of the three
retries.

That is the opposite of what this project does everywhere else: `plan_catalogue_reconcile`,
`embedding_reconcile`, `encryption_reconcile` and `plan_grant_reconcile` each wrap their
**idempotent** work in `pg_try_advisory_xact_lock`, while the one piece of **non-idempotent
DDL** runs unguarded.

Concretely: a deploy carrying a new migration restarts both process types at once, both read
the same revision from `alembic_version`, both plan the same `op.add_column`, and the second
blocks on the first's `ACCESS EXCLUSIVE` lock before failing on a column that now exists.

The lock here is **session-level and blocking** (`pg_advisory_lock`), not the `try_` form the
reconciles use. They are right to skip when another dyno holds it — their work is idempotent
and will be done by whoever holds the lock. This one must not skip: the caller's next line
assumes the schema is at head, so a migration that quietly did not run is worse than one
that waited.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models import base as base_mod


class TestPostgresMigrationsSerialise:
    def test_the_lock_is_taken_and_released_around_alembic(self) -> None:
        calls: list[str] = []
        conn = MagicMock()
        conn.execute.side_effect = lambda sql, *a, **kw: calls.append(str(sql))
        ctx = MagicMock()
        ctx.__enter__.return_value = conn

        with (
            patch.object(base_mod, "_migration_lock_connection", return_value=ctx),
            patch.object(base_mod.settings, "database_url", "postgresql+asyncpg://u@h/db"),
            patch("subprocess.run") as run,
        ):
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            base_mod.run_migrations()

        joined = " ".join(calls).lower()
        assert "pg_advisory_lock" in joined, (
            "alembic ran with no advisory lock: two process types migrating the same "
            "database concurrently is the one piece of non-idempotent DDL this codebase "
            "leaves unguarded (DATA-10)"
        )
        assert "pg_advisory_unlock" in joined, (
            "the session-level lock is never released, so the next deploy's migration "
            "waits on a connection nobody closed"
        )
        assert run.called, "the migration itself did not run"

    def test_the_lock_is_released_even_when_the_migration_fails(self) -> None:
        conn = MagicMock()
        released: list[str] = []
        conn.execute.side_effect = lambda sql, *a, **kw: released.append(str(sql))
        ctx = MagicMock()
        ctx.__enter__.return_value = conn

        import subprocess

        with (
            patch.object(base_mod, "_migration_lock_connection", return_value=ctx),
            patch.object(base_mod.settings, "database_url", "postgresql+asyncpg://u@h/db"),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "alembic")),
        ):
            try:
                base_mod.run_migrations()
            except Exception:
                pass

        assert any("pg_advisory_unlock" in s.lower() for s in released), (
            "a failed migration leaves the lock held, so every later deploy hangs on it"
        )


class TestSqliteIsUntouched:
    def test_no_lock_is_attempted_without_postgres(self) -> None:
        """A `make setup` install has no advisory locks and needs none — one process."""
        with (
            patch.object(base_mod.settings, "database_url", "sqlite+aiosqlite:///./data/agent.db"),
            patch.object(base_mod, "_migration_lock_connection") as conn_factory,
            patch("subprocess.run") as run,
        ):
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            base_mod.run_migrations()

        conn_factory.assert_not_called()
        assert run.called, "the migration must still run on SQLite"
