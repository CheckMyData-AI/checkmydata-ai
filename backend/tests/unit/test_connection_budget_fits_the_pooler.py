"""The app's connection demand must be checkable against the pooler's limit.

Measured on production 2026-09-09, by saturating it. Supavisor in session mode caps the
project at `pool_size: 15`. The application is configured to want more than twice that:

    SQLAlchemy   db_pool_size 5 + db_pool_overflow 10   ->  up to 15 per process
    PgVectorStore psycopg pool  max(2, 5 // 2)          ->            2 per process
                                                             up to 17 per process
    web + worker                                             up to 34

It survived only because the pools are lazy — at rest 7 per process, 14 of 15 — so there
was no headroom at all, and any overflow connection, one-off dyno or `psql` session pushed
it over:

    02:43:21  web  psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec
              ext  FATAL: (EMAXCONNSESSION) max clients reached in session mode

`/api/health` stayed 200 throughout, because already-open connections keep working. That
is why nobody noticed: the failure mode is invisible from the outside and the arithmetic
lived in three files that never referred to each other.

So the fix here is not a number — it is making the arithmetic **fail at boot** when it
does not fit. `db_connection_ceiling` is what the pooler allows; when set, the worst case
is computed from the same settings the pools are built from and compared to it. Whoever
raises the pooler raises the pools in the same change, or the boot refuses.

Default `0` means "no ceiling declared" and checks nothing, because a self-hosted install
talking straight to Postgres has no such limit and must not be throttled by one.
"""

from __future__ import annotations

import pytest

from app.config import Settings, worst_case_connections_per_process


class TestTheArithmeticHasOneHome:
    def test_it_counts_every_pool_a_process_opens(self) -> None:
        """Both pools, because both are real. The psycopg one was the invisible half —
        it is built inside `PgVectorStore`, not beside the SQLAlchemy engine."""
        n = worst_case_connections_per_process(pool_size=5, overflow=10)
        assert n == 17, f"expected 5 + 10 + max(2, 5 // 2) = 17, got {n}"

    def test_it_matches_what_pgvector_actually_opens(self) -> None:
        """Pinned against the store's own expression rather than a copy of it: two
        formulas that must agree are two formulas that will not."""
        from app.config import _pgvector_pool_size, settings
        from app.knowledge.pgvector_store import _pool_max_size

        # The VALUE, from the store's own helper, at several pool sizes. This used to
        # assert the literal source text `"max(2, settings.db_pool_size // 2)"`
        # (TEST-09): a comment anywhere in the module satisfied it, and rewriting the
        # identical arithmetic as `>> 1` broke it. Two formulas that must agree are
        # two formulas that will not — so there is one now, and this reads it.
        for pool in (1, 2, 4, 10, 40):
            original = settings.db_pool_size
            try:
                settings.db_pool_size = pool
                assert _pool_max_size() == _pgvector_pool_size(pool), (
                    "the store's pool size moved; `worst_case_connections_per_process` "
                    "is now computing a different number from the one the process opens"
                )
            finally:
                settings.db_pool_size = original

    @pytest.mark.parametrize(
        "pool,overflow,expected",
        [(1, 0, 1 + 0 + 2), (4, 1, 4 + 1 + 2), (10, 0, 10 + 0 + 5)],
    )
    def test_the_vector_pool_scales_with_the_main_one(
        self, pool: int, overflow: int, expected: int
    ) -> None:
        assert worst_case_connections_per_process(pool_size=pool, overflow=overflow) == expected


class TestTheCeilingIsEnforcedAtBoot:
    def test_no_ceiling_declared_checks_nothing(self) -> None:
        """A self-hosted install talking straight to Postgres has no pooler limit. The
        default must not throttle it, and must not raise on today's numbers."""
        s = Settings(db_connection_ceiling=0, db_pool_size=5, db_pool_overflow=10)
        assert s.db_connection_ceiling == 0

    def test_a_configuration_that_cannot_fit_refuses_to_boot(self) -> None:
        """The production shape: 17 per process, two process types, ceiling 15."""
        with pytest.raises(ValueError, match="DB_CONNECTION_CEILING"):
            Settings(db_connection_ceiling=15, db_pool_size=5, db_pool_overflow=10)

    def test_the_message_carries_the_arithmetic(self) -> None:
        """An operator's next move is to raise the pooler or lower the pools, and both
        need the four numbers. "Too many connections" is not actionable."""
        with pytest.raises(ValueError) as exc:
            Settings(db_connection_ceiling=15, db_pool_size=5, db_pool_overflow=10)
        msg = str(exc.value)
        for fragment in ("17", "15", "db_pool_size", "db_pool_overflow"):
            assert fragment in msg, f"{fragment!r} missing from {msg!r}"

    def test_a_configuration_that_fits_boots(self) -> None:
        """4 + 1 + 2 = 7 per process, 14 across two, one spare for an operator session."""
        s = Settings(db_connection_ceiling=15, db_pool_size=4, db_pool_overflow=1)
        assert (
            worst_case_connections_per_process(
                pool_size=s.db_pool_size, overflow=s.db_pool_overflow
            )
            == 7
        )

    def test_it_reserves_one_connection_for_a_human(self) -> None:
        """The saturation was found by a `psql` session failing. A budget that fills the
        pooler exactly leaves nobody able to look at the database while it is busy —
        which is precisely when somebody needs to."""
        # 7 per process x 2 = 14 fits under 15; 8 x 2 = 16 does not, and neither does the
        # boundary case 7.5. The reserve is what makes 15 -> 7 rather than 15 -> 7.5.
        Settings(db_connection_ceiling=15, db_pool_size=4, db_pool_overflow=1)
        with pytest.raises(ValueError):
            Settings(db_connection_ceiling=15, db_pool_size=4, db_pool_overflow=2)
