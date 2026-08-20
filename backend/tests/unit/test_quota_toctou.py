"""F-BILL-02 — the quota check counted, compared, and then the caller inserted.

`enforce_connection_quota` runs `SELECT COUNT(…)` and raises when the count has reached the
plan's limit. The insert happens afterwards, in the route. Two concurrent requests both
count `N-1`, both pass the check, and both insert: a plan allowing one connection ends up
with two.

Creation is rate-limited to 10/minute, which bounds how far it goes and does not stop it —
a free plan is one connection, and two parallel requests are enough.

**The fix is a row lock on the owner, taken before the count.** `SELECT … FOR UPDATE` on the
`users` row serialises quota checks for that user and leaves different users uncontended.

It is honest about where it works. `FOR UPDATE` is a Postgres guarantee; SQLite's driver
accepts the clause and ignores it. Production is Postgres, and dev on SQLite is a
single-writer database where two transactions cannot interleave the way this race needs — so
the guard is real where the race is real, and inert where it cannot happen. These tests
assert the lock is *requested*, because asserting that it *serialises* is something SQLite
cannot be made to demonstrate, and a test that pretends otherwise is worse than none.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.services.entitlement_service import EntitlementService


def _source_of(name: str) -> str:
    return textwrap.dedent(inspect.getsource(getattr(EntitlementService, name)))


class TestTheLockItself:
    def test_lock_owner_requests_for_update(self):
        """Checked on the AST rather than by string, so a comment mentioning
        `with_for_update` cannot satisfy it — the mistake made earlier today in the
        invite-savepoint test, which failed against its own explanatory prose."""
        tree = ast.parse(_source_of("_lock_owner"))
        locks = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "with_for_update"
        ]

        assert locks, "_lock_owner does not actually take a lock"

    def test_a_lock_failure_does_not_block_the_request(self):
        """A database that cannot take the lock must not refuse the write: the count that
        follows is still correct in the common case, and failing hard would trade a rare
        over-count for an outage. The warning is how anyone finds out."""
        tree = ast.parse(_source_of("_lock_owner"))
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]

        assert handlers, "a lock failure propagates and turns a quota check into a 500"

        # The handler has to be broad, and the first version of this test could not tell.
        # Changing `except Exception` to `except SystemExit` left it green: it asserted
        # that *an* except existed and that *something* logged a warning, both of which
        # stayed true while the guard stopped guarding. A driver that raises its own
        # OperationalError is exactly the case this exists for.
        broad = [
            h
            for h in handlers
            if h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
        ]
        assert broad, (
            "the handler is narrower than the failures it must absorb — a driver-specific "
            "error would escape and turn a quota check into a 500"
        )
        assert any(
            isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "warning"
            for h in broad
            for c in ast.walk(h)
        ), "a swallowed lock failure with nothing logged is the silent-degradation shape"


@pytest.mark.parametrize("method", ["enforce_connection_quota", "enforce_project_quota"])
class TestBothQuotasTakeItBeforeCounting:
    def test_the_lock_is_taken(self, method):
        assert "_lock_owner" in _source_of(method), (
            f"{method} counts without serialising concurrent checks for the owner"
        )

    def test_it_comes_before_the_count(self, method):
        """A lock taken after the count serialises nothing: both racers have already read
        the value they will act on."""
        tree = ast.parse(_source_of(method))
        lock_lines = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "_lock_owner"
        ]
        count_lines = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "count"
        ]

        assert lock_lines, f"{method} takes no lock"
        assert count_lines, "no COUNT here — the test is looking at the wrong thing"
        assert min(lock_lines) < min(count_lines)

    def test_an_unlimited_plan_returns_before_the_lock(self, method):
        """Locking a row to decide nothing is contention bought for free."""
        src = _source_of(method)
        early_return = src.index("return")
        lock = src.index("_lock_owner")

        assert early_return < lock


class TestTheCheckStillDoesItsJob:
    async def test_it_passes_under_the_limit(self, monkeypatch):
        svc = EntitlementService()
        monkeypatch.setattr(
            svc, "get_entitlements", _entitlements(max_connections=5, max_projects=5)
        )

        await svc.enforce_connection_quota(_db(count=2), "u1")

    async def test_it_refuses_at_the_limit(self, monkeypatch):
        from app.services.entitlement_service import QuotaExceededError

        svc = EntitlementService()
        monkeypatch.setattr(
            svc, "get_entitlements", _entitlements(max_connections=2, max_projects=5)
        )

        with pytest.raises(QuotaExceededError) as exc:
            await svc.enforce_connection_quota(_db(count=2), "u1")
        assert exc.value.limit == 2
        assert exc.value.current == 2

    async def test_an_unlimited_plan_takes_no_lock(self, monkeypatch):
        """Locking a row to decide nothing is contention bought for free. An unlimited
        plan returns before the lock."""
        svc = EntitlementService()
        monkeypatch.setattr(
            svc, "get_entitlements", _entitlements(max_connections=0, max_projects=0)
        )
        db = _db(count=99)

        await svc.enforce_connection_quota(db, "u1")

        assert db.executed == 0, "an unlimited plan queried the database"


def _entitlements(*, max_connections: int, max_projects: int):
    from app.services.entitlement_service import Entitlements

    async def _get(_db, _uid):
        return Entitlements(
            plan_id="p",
            plan_name="Test",
            status="active",
            max_connections=max_connections,
            max_projects=max_projects,
            seats=1,
            daily_token_limit=0,
            monthly_token_limit=0,
            cancel_at_period_end=False,
            current_period_end=None,
        )

    return _get


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    """Answers the lock query with a row and the count query with a number."""

    def __init__(self, count: int):
        self._count = count
        self.executed = 0

    async def execute(self, stmt):
        self.executed += 1
        text = str(stmt).lower()
        if "count(" in text:
            return _Result(self._count)
        return _Result("u1")


def _db(*, count: int) -> _Db:
    return _Db(count)
