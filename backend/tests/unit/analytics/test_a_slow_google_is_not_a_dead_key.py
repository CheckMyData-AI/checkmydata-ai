"""T06b — the GA4 residue, before the first real GA4 connection meets it.

Audit 2026-09-23 §3.4 (`docs/audits/2026-09-23-recent-work-audit.md`):

* F-G1 — `_is_auth_failure` treated every `google.auth.exceptions.GoogleAuthError` as a
  credential that will never work again. `TransportError` and `TimeoutError` are
  subclasses of it, so a network blip during the token refresh journalled the report
  `failed` instead of retrying it, and `POST /vendor-credentials/{id}/verify` stamped a
  working key as refused — the one thing its docstring promises never to do.
"""

from __future__ import annotations

import pytest
from google.auth import exceptions as gae

from app.analytics.errors import AnalyticsAuthError, AnalyticsTransientError
from app.analytics.ga4.adapter import _is_auth_failure, _map_client_error


@pytest.mark.parametrize(
    "exc",
    [
        gae.TransportError("connection reset by peer"),
        gae.TimeoutError("read timed out"),
        gae.RefreshError("token endpoint 503", retryable=True),
    ],
)
def test_a_network_failure_during_the_refresh_is_not_a_dead_key(exc) -> None:
    assert _is_auth_failure(exc) is False
    assert isinstance(_map_client_error(exc), AnalyticsTransientError)


def test_one_wrapped_by_the_call_is_not_either() -> None:
    wrapper = RuntimeError("503 Service Unavailable")
    wrapper.__cause__ = gae.TransportError("connection reset")
    assert _is_auth_failure(wrapper) is False


@pytest.mark.parametrize(
    "exc",
    [
        gae.RefreshError("invalid_grant: account not found"),
        gae.RefreshError("invalid_grant", retryable=False),
        gae.DefaultCredentialsError("malformed service-account file"),
    ],
)
def test_a_refused_credential_still_is(exc) -> None:
    assert _is_auth_failure(exc) is True
    assert isinstance(_map_client_error(exc), AnalyticsAuthError)


def test_the_words_of_a_revoked_key_win_over_a_transport_wrapper() -> None:
    """A-02's marker rule stands: the cause says the key is revoked."""
    exc = gae.TransportError("metadata plugin failed: invalid_grant")
    assert _is_auth_failure(exc) is True


# F-G2 — the journal's `partial` (A-01: a property did not answer; A-04: the day may
# not have been over) was read by nothing in the agent, so such a period was published
# under "all periods collected, so the values below are real measurements".


def _statuses():
    return {
        "2026-09-19": ("ok", None),
        "2026-09-20": ("partial", "property 222 did not answer: 503"),
    }


def test_a_partial_period_is_named_and_the_coverage_claim_is_withheld() -> None:
    from app.agents.analytics_agent import AnalyticsAgent, _partial_periods, _Window

    statuses = _statuses()
    partial = _partial_periods(list(statuses), statuses)
    assert partial == ["2026-09-20: property 222 did not answer: 503"]

    window = _Window(
        report="overview",
        start="2026-09-19",
        end="2026-09-20",
        missing=[],
        failed=[],
        last_error=None,
        partial=partial,
    )
    agent = AnalyticsAgent()
    header = "\n".join(agent._window_coverage_lines(window, list(statuses)))
    assert "INCOMPLETE" in header and "2026-09-20" in header
    assert "real measurements" not in header, "the coverage claim contradicts the caveat"

    caveats = " ".join(agent._window_partial_caveats(window))
    assert "2026-09-20" in caveats and "collected again" in caveats


def test_a_partial_period_is_not_degraded_or_provisional_too() -> None:
    from app.agents.analytics_agent import _degraded_periods, _provisional_periods

    statuses = _statuses()
    assert _degraded_periods(list(statuses), statuses) == []
    assert _provisional_periods(list(statuses), statuses) == []


# F-G3 / F-G4 — Verify recorded "cannot be checked yet" as a refusal of an untested
# `appstore`/`googleplay` key, and an undecryptable row was an unhandled 500.


class _Row:
    def __init__(self, provider: str, secret_encrypted: str) -> None:
        self.id = "cred-1"
        self.provider = provider
        self.secret_encrypted = secret_encrypted
        self.last_verified_at = None
        self.last_verify_error = None


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_a_key_nothing_can_check_is_not_recorded_as_refused(monkeypatch) -> None:
    from app.analytics.errors import AnalyticsNotVerifiableError
    from app.services import vendor_credential_service as svc_mod
    from app.services.encryption import encrypt

    row = _Row("appstore", encrypt("-----p8-----"))
    service = svc_mod.VendorCredentialService()

    async def _get(session, credential_id, user_id=None):
        return row

    monkeypatch.setattr(service, "get", _get)
    session = _Session()
    with pytest.raises(AnalyticsNotVerifiableError):
        await service.verify(session, "cred-1", user_id="u")
    assert row.last_verify_error is None and row.last_verified_at is None
    assert session.commits == 0


@pytest.mark.asyncio
async def test_an_undecryptable_row_says_so_and_records_nothing(monkeypatch) -> None:
    from app.services import vendor_credential_service as svc_mod

    row = _Row("ga4", "not-a-fernet-token")
    service = svc_mod.VendorCredentialService()

    async def _get(session, credential_id, user_id=None):
        return row

    monkeypatch.setattr(service, "get", _get)
    with pytest.raises(ValueError, match="encryption key"):
        await service.verify(_Session(), "cred-1", user_id="u")
    assert row.last_verify_error is None
