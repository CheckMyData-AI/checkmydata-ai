"""Two processes cannot start the same indexing run, and this proves it rather than
asserting it.

`CLAUDE.md` said, from 2026-09-01: *"Still open: repo-index mutual exclusion is
per-process only. `_indexing_locks` (`repos.py:53`) is a module-level dict of
`asyncio.Lock`, while the entry points span both process types."*

That sentence names a real thing — the dict IS per-process — and draws the wrong
conclusion from it, because the dict is not what makes exclusion work. Three facts,
each checked here rather than recalled:

1. **`IndexingRun` is constructed in exactly one place**, `RunCoordinator.start`
   (`run_coordinator.py:281`). There is no path that mints a run around the coordinator,
   so there is nothing for a second mechanism to guard.
2. **The exclusion is enforced by the database**, not by the pre-check.
   `uq_indexing_runs_active_one` is a partial unique index on
   `(project_id, kind, coalesce(connection_id, ''))` restricted to
   `status IN ('queued','running','cancelling')` — declared for **both** SQLite and
   PostgreSQL (`indexing_run.py:85-92`), so this file's assertions are the shipped
   behaviour and not a dialect-specific approximation.
3. **The TOCTOU window is closed by catching `IntegrityError`**, not by hoping the
   pre-check wins. `start` rolls back — mandatory, the session is poisoned otherwise —
   re-queries for the winner, and raises `RunAlreadyActiveError` carrying its id.

What the September 1st incident actually was, for the record: not a missing lock. The
reaper flipped a live run's row to `failed`, and `_find_active` filtered on **status** —
the one field a wrong reap falsifies — so the coordinator was asked "is one active?"
about a row that had been declared dead while it worked. That is closed by `_is_live`,
which trusts `heartbeat_at` for exactly the two provisional states.

So the remaining honest statement is narrower than the old one: `_indexing_locks` is a
fast path that avoids a database round trip in the common case, not a correctness
mechanism. A Redis lock would add nothing here — and its TTL would have to be renewed by
the same heartbeat that failed on September 1st.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.indexing_run import IndexingRun


@pytest_asyncio.fixture
async def engine():
    # NOT `?cache=shared`. The first version used it, and a shared-cache in-memory
    # database is process-global: `tests/conftest.py` points the whole suite's
    # `DATABASE_URL` at `sqlite+aiosqlite:///:memory:`, so the `IndexingRun` rows this
    # file inserts became visible to `async_session_factory` and made
    # `RunCoordinator._find_active` report an active run to unrelated tests. Four of them
    # went red in the full suite while passing in isolation, which is the signature.
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


class TestTheDatabaseEnforcesIt:
    async def test_the_partial_unique_index_exists_on_this_dialect(self, engine) -> None:
        """The premise of everything below. If the index is not created, the tests that
        follow would pass on the Python pre-check alone and prove nothing about a second
        process."""
        from sqlalchemy import text

        async with engine.connect() as conn:
            names = {
                r[0]
                for r in (
                    await conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
                ).all()
            }
        assert "uq_indexing_runs_active_one" in names

    async def test_a_second_active_run_is_refused_by_the_database_itself(self, engine) -> None:
        """Bypassing `RunCoordinator` entirely and inserting the row by hand: the
        constraint must hold even against code that never consulted `_find_active`,
        because that is what "another process" means.
        """
        from sqlalchemy.exc import IntegrityError

        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        def _row(wf: str) -> IndexingRun:
            return IndexingRun(
                workflow_id=wf,
                project_id="p1",
                connection_id=None,
                kind="index_repo",
                trigger="manual",
                status="running",
                step_index=0,
                total_steps=5,
                progress_pct=0,
            )

        async with factory() as a:
            a.add(_row("wf-a"))
            await a.commit()

        async with factory() as b:
            b.add(_row("wf-b"))
            with pytest.raises(IntegrityError):
                await b.commit()

    async def test_a_finished_run_stops_blocking_the_next_one(self, engine) -> None:
        """The index is partial for a reason: history must not make a project
        permanently un-indexable."""
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as a:
            run = IndexingRun(
                workflow_id="wf-done",
                project_id="p2",
                connection_id=None,
                kind="index_repo",
                trigger="manual",
                status="running",
                step_index=0,
                total_steps=5,
                progress_pct=0,
            )
            a.add(run)
            await a.commit()
            run.status = "completed"
            await a.commit()

        async with factory() as b:
            b.add(
                IndexingRun(
                    workflow_id="wf-next",
                    project_id="p2",
                    connection_id=None,
                    kind="index_repo",
                    trigger="manual",
                    status="running",
                    step_index=0,
                    total_steps=5,
                    progress_pct=0,
                )
            )
            await b.commit()  # must not raise

    async def test_two_connections_of_one_project_are_independent(self, engine) -> None:
        """`coalesce(connection_id, '')` is in the index precisely so a NULL-connection
        run (repo index) and a per-connection one (db index) do not collide, while two
        NULL ones still do."""
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as s:
            for wf, conn_id in (("wf-c1", "c1"), ("wf-c2", "c2")):
                s.add(
                    IndexingRun(
                        workflow_id=wf,
                        project_id="p3",
                        connection_id=conn_id,
                        kind="db_index",
                        trigger="manual",
                        status="running",
                        step_index=0,
                        total_steps=5,
                        progress_pct=0,
                    )
                )
            await s.commit()  # must not raise


class TestNothingMintsARunAroundTheCoordinator:
    def test_indexing_run_is_constructed_in_exactly_one_place(self) -> None:
        """The claim the old CLAUDE.md paragraph rested on — that entry points span two
        process types — is true and irrelevant, because they all converge here. If a
        second construction site appears, the guarantee this file documents is gone and
        this test is how anyone finds out."""
        import pathlib
        import re

        app_dir = pathlib.Path(__file__).resolve().parents[3] / "app"
        sites: list[str] = []
        for path in app_dir.rglob("*.py"):
            if path.name == "indexing_run.py":
                continue  # the model's own class statement
            for i, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(r"\bIndexingRun\(", stripped):
                    sites.append(f"{path.relative_to(app_dir)}:{i}")

        assert sites == ["services/run_coordinator.py:281"], (
            "IndexingRun is constructed somewhere other than RunCoordinator.start, so a "
            f"run can be minted without the exclusion check: {sites}"
        )

    def test_the_toctou_window_is_closed_by_catching_the_constraint(self) -> None:
        """The pre-check alone is a race. What makes it safe is that losing the race is
        handled rather than raised at the caller as an opaque database error — and that
        the session is rolled back first, without which it stays poisoned."""
        import inspect
        import re

        from app.services import run_coordinator as mod

        src = inspect.getsource(mod.RunCoordinator.start)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert "IntegrityError" in body, "the constraint violation is not handled"
        assert "rollback" in body, (
            "the session must be rolled back after an IntegrityError or it stays poisoned"
        )
        assert "RunAlreadyActiveError" in body


class TestTheInMemoryLockIsNotTheMechanism:
    def test_it_is_documented_as_a_fast_path(self) -> None:
        """Not deleted — it does save a round trip, and the dispatch paths read better
        with it. But a reader who takes it for the correctness mechanism will "fix" the
        wrong thing when two agents next collide, which is what the old note invited."""
        import inspect

        from app.api.routes import repos

        src = inspect.getsource(repos)
        idx = src.index("_indexing_locks")
        window = src[max(0, idx - 900) : idx + 900]
        assert "RunCoordinator" in window, (
            "the lock's comment must point at what actually enforces exclusion, or the "
            "next reader will build a Redis lock nobody needs"
        )
