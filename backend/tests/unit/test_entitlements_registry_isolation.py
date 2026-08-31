"""The `autouse` reset in `conftest.py`, and a pair that actually proves it works.

`app.entitlements` holds one provider for the whole process — right in production, where it
is installed once at start-up, and a hazard in a suite, where a test that installs a
refusing provider and forgets to reset leaves every later test facing a 402 it never asked
for.

**Deliberately its own file, with no local fixture.** The first version of this pair lived
in `test_entitlements_seam.py`, which has its own `autouse` reset at the top — so it passed
with the conftest fixture deleted and proved nothing at all. Verified here by removing the
fixture and watching the second test go red.

Found the long way round: one integration test failed in a full run and passed alone. That
reads as "flaky"; it was a global with a hand-written reset in three files.
"""

from __future__ import annotations


def test_a_provider_is_installed_and_never_reset() -> None:
    """Half of a pair. This one leaks on purpose."""
    from app.entitlements import set_entitlements

    class _Refuse:
        async def enforce_project_quota(self, db, user_id):
            raise RuntimeError("leaked")

        async def enforce_connection_quota(self, db, user_id):
            raise RuntimeError("leaked")

        async def effective_token_limits(self, db, user_id):
            return (1, 1)

    set_entitlements(_Refuse())  # deliberately not reset


def test_the_next_test_still_sees_the_default() -> None:
    """The other half. Red if the conftest reset is gone or stops applying here."""
    from app.entitlements import UnlimitedEntitlements, get_entitlements

    assert isinstance(get_entitlements(), UnlimitedEntitlements), (
        "a provider leaked from the previous test — the autouse reset in conftest.py is "
        "missing, or no longer reaches this file"
    )
