"""Presence tests for slowapi rate limits on mutation endpoints (audit N-1).

The limiter records static per-route limits at import time, keyed by
``<module>.<function>``; these tests guard against accidentally dropping a
``@limiter.limit`` decorator from a sensitive mutation. They complement
tests/unit/test_rate_limit.py, which covers the Limiter configuration itself.
"""

# Importing the route modules registers their @limiter.limit decorators.
from app.api.routes import billing, chat, data_investigations, schedules  # noqa: F401
from app.core.rate_limit import limiter


def _limit_strings(qualname: str) -> list[str]:
    """Flatten the limiter's per-route registry entry into limit strings."""
    entries = limiter._route_limits.get(qualname, [])
    strings: list[str] = []
    for entry in entries:
        try:
            iterator = iter(entry)
        except TypeError:
            iterator = iter([entry])
        for lim in iterator:
            strings.append(str(getattr(lim, "limit", lim)).lower())
    return strings


def _assert_limited(qualname: str, value: str) -> None:
    strings = _limit_strings(qualname)
    assert strings, f"{qualname} has no rate limit registered"
    assert any(value in s and "minute" in s for s in strings), (
        f"{qualname}: expected a {value}/minute limit, got {strings}"
    )


def test_billing_checkout_is_rate_limited() -> None:
    _assert_limited("app.api.routes.billing.create_checkout", "10")


def test_billing_portal_is_rate_limited() -> None:
    _assert_limited("app.api.routes.billing.create_portal", "10")


def test_schedules_update_is_rate_limited() -> None:
    _assert_limited("app.api.routes.schedules.update_schedule", "10")


def test_confirm_fix_is_rate_limited() -> None:
    _assert_limited("app.api.routes.data_investigations.confirm_investigation_fix", "10")


def test_ws_ticket_is_rate_limited() -> None:
    _assert_limited("app.api.routes.chat.issue_ws_ticket", "30")
