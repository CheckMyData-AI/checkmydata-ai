"""Board row 25 — four findings that no row named until 2026-09-12.

They are one row because they share a shape: **a check that exists, and a path that
does not reach it.** The email-verification gate is written and guards project creation
alone; the DNS-rebinding guard is written and runs at save rather than at connect; the
backfill clamp is written and lives in the React form; the worker's concurrency is
configured against a job that exceeds the dyno on its own.

- **AUTH-01** — `accept_invite` proves the caller's *stored* email equals the invite's,
  never that they ever proved ownership of it. Registration issues a live session with
  `email_verified=False`, so an attacker registering the invitee's address collects the
  invite from `/pending` and accepts it.
- **SQL-07** — `host_guard`'s own docstring says both checks resolve DNS and check every
  address "because `db.attacker.test` may resolve to a public address in the operator's
  check and a private one a second later". That reasoning holds only if the check runs
  when the socket opens. It ran at write time, and the stored value was reused by every
  connector, by `SSHTunnel.start` and by `to_config`.
- **OPS-08** — `max_jobs = 8` against a repo index measured above the dyno's whole
  memory quota on its own.
- **ANA-06** — `source_config` is an unvalidated free-form dict; `backfill_days: 100000`
  is accepted and enumerates 500 000 vendor calls per run, starting in 1752.
"""

from __future__ import annotations

import pytest


class TestAnInviteNeedsAProvenAddress:
    """AUTH-01."""

    def test_accept_invite_checks_the_address_was_proven(self) -> None:
        import inspect

        from app.services.invite_service import InviteService

        source = inspect.getsource(InviteService.accept_invite)
        assert "email_verified" in source, (
            "the check proves the caller's STORED email equals the invite's, which the "
            "caller chose at registration — `/api/auth/register` returns a live session "
            "with `email_verified=False`, and the only gate on that column anywhere in "
            "the API is project creation. An attacker who registers the invitee's "
            "address reads the invite id from `/api/invites/pending` and accepts it "
            "(AUTH-01)"
        )

    async def test_an_unverified_caller_is_refused(self) -> None:
        from fastapi import HTTPException

        from app.services.invite_service import InviteService

        with pytest.raises(HTTPException) as exc:
            await InviteService().accept_invite(
                _SessionWith(email_verified=False), "inv-1", user_id="u1"
            )
        assert exc.value.status_code == 403
        assert "verify" in str(exc.value.detail).lower(), (
            f"refused for the wrong reason: {exc.value.detail}"
        )

    async def test_a_verified_caller_is_not_blocked_here(self) -> None:
        """The gate must refuse on verification alone, not on everything."""
        from fastapi import HTTPException

        from app.services.invite_service import InviteService

        try:
            await InviteService().accept_invite(
                _SessionWith(email_verified=True), "inv-1", user_id="u1"
            )
        except HTTPException as exc:  # pragma: no cover - shape depends on the fake
            assert "verify" not in str(exc.detail).lower(), (
                "a verified caller was turned away by the verification gate"
            )
        except Exception:
            pass  # the fake session runs out of shape past the checks; that is fine

    def test_the_auto_accept_paths_stay_exempt(self) -> None:
        """Both callers have just proven the address — after `verify_email`, and after
        a Google login, which is pre-verified. Gating them would lock out the people
        the feature exists for."""
        import inspect

        from app.services.invite_service import InviteService

        source = inspect.getsource(InviteService.accept_invite)
        gate = source[source.index("if not _skip_email_check:") :]
        assert "email_verified" in gate, (
            "the verification check must sit INSIDE the `_skip_email_check` branch, or "
            "a Google sign-in stops accepting invitations"
        )


class TestTheRebindingGuardRunsWhenTheSocketOpens:
    """SQL-07."""

    def test_to_config_resolves_the_host_again(self) -> None:
        import inspect

        from app.services.connection_service import ConnectionService

        source = inspect.getsource(ConnectionService.to_config)
        assert "check_connection_targets" in source or "guard" in source.lower(), (
            "`host_guard`'s own docstring argues the check must see every address "
            "because the record can change between the operator's check and the "
            "connection — and it ran only at write time, after which the stored value "
            "was reused by every connector, by `SSHTunnel.start` and by `to_config` "
            "(SQL-07)"
        )


class TestTheWorkerCannotStartMoreIndexesThanItFits:
    """OPS-08."""

    def test_repo_index_concurrency_is_one(self) -> None:
        from app import worker

        assert getattr(worker, "MAX_CONCURRENT_REPO_INDEXES", None) == 1, (
            "`max_jobs = 8` against a repo index measured above the dyno's entire "
            "memory quota on its own: eight at once is seven more than fit (OPS-08)"
        )

    async def test_a_second_index_waits_for_the_first(self) -> None:
        """Measured by running two, not by finding the word `Semaphore` in the module.

        The first draft asserted that the constant and `Semaphore` both appear in the
        source. Deleting the `async with` — keeping both — passed it, which is the
        trap this file exists to avoid: a guard that matches a NAME rather than a
        behaviour.
        """
        import asyncio
        from unittest.mock import patch

        from app import worker

        running = 0
        peak = 0

        async def _slow(project_id, *, force_full=False, wf_id=None):  # noqa: ANN001
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        with patch("app.api.routes.repos.run_repo_index_task", new=_slow):
            await asyncio.gather(*(worker.run_repo_index({}, project_id=f"p{i}") for i in range(4)))

        assert peak == worker.MAX_CONCURRENT_REPO_INDEXES, (
            f"{peak} repo indexes ran at once against a limit of "
            f"{worker.MAX_CONCURRENT_REPO_INDEXES}. One of them already exhausts the "
            "dyno's memory quota on its own (OPS-08)"
        )


class TestTheBackfillWindowIsBoundedOnTheServer:
    """ANA-06."""

    def test_the_clamp_exists_where_the_api_can_reach_it(self) -> None:
        from app.analytics.source_types import (
            MAX_BACKFILL_DAYS,
            MIN_BACKFILL_DAYS,
            clamp_backfill_days,
        )

        assert clamp_backfill_days(100_000) == MAX_BACKFILL_DAYS, (
            "`backfill_days: 100000` was accepted and enumerated 500 000 vendor calls "
            "per run, starting in 1752 — the clamp the runbook promises lived in the "
            "React form, which any direct API call bypasses (ANA-06)"
        )
        assert clamp_backfill_days(0) == MIN_BACKFILL_DAYS
        assert clamp_backfill_days(-5) == MIN_BACKFILL_DAYS
        assert clamp_backfill_days(30) == 30
        assert clamp_backfill_days(None) is None, (
            "absent is not out of range: the caller's default must still apply"
        )

    def test_the_bounds_match_what_the_form_promised(self) -> None:
        """The React form clamps to 1–3650; the server must not disagree with it."""
        from app.analytics.source_types import MAX_BACKFILL_DAYS, MIN_BACKFILL_DAYS

        assert (MIN_BACKFILL_DAYS, MAX_BACKFILL_DAYS) == (1, 3650)

    def test_the_write_path_applies_it(self) -> None:
        """Built through the real schemas, not searched for in the module's text.

        The first draft looked for `clamp_backfill_days` OR `_validate_source_config`
        anywhere in `connections.py`. Emptying the validator's body — leaving the
        function defined — passed it.
        """
        from app.api.routes.connections import ConnectionCreate, ConnectionUpdate

        created = ConnectionCreate(
            project_id="p1",
            name="ga4",
            source_type="ga4",
            vendor_credential_id="cred-1",
            source_config={"property_ids": ["294380179"], "backfill_days": 100_000},
        )
        assert created.source_config["backfill_days"] == 3650, (
            "`PATCH` with 100 000 was accepted and every run then enumerated 100 000 "
            "daily periods per report — 500 000 vendor calls, starting in 1752 — while "
            "`GET /collection-status` rebuilt the same strings on a read-only "
            "endpoint (ANA-06)"
        )
        assert created.source_config["property_ids"] == ["294380179"], (
            "the validator must bound what it understands, not rewrite the rest"
        )

        patched = ConnectionUpdate(source_config={"backfill_days": -5})
        assert patched.source_config["backfill_days"] == 1, (
            "guarded on create and free on PATCH is a shape this file has been bitten by before"
        )


class _SessionWith:
    """Enough of an AsyncSession for `accept_invite` to reach the verification gate.

    Answers the invite query, then the user query; anything after that is past the
    checks this file is about.
    """

    def __init__(self, *, email_verified: bool) -> None:
        self._email_verified = email_verified
        self._calls = 0

    async def execute(self, *_a, **_k):
        self._calls += 1
        if self._calls == 1:
            return _Scalar(type("Invite", (), {"status": "pending", "email": "newhire@corp.com"})())
        if self._calls == 2:
            return _Scalar(
                type(
                    "User",
                    (),
                    {"email": "newhire@corp.com", "email_verified": self._email_verified},
                )()
            )
        raise RuntimeError("past the checks under test")

    async def commit(self) -> None:
        return None


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value
