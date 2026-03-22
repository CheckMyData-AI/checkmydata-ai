"""Unit tests for app.core.rate_limit Limiter configuration."""

from slowapi.util import get_remote_address

from app.core.rate_limit import limiter


def test_limiter_instance_exists() -> None:
    assert limiter is not None
    assert limiter.__class__.__name__ == "Limiter"


def test_default_limit_is_60_per_minute() -> None:
    assert limiter._default_limits, "expected default_limits from Limiter constructor"
    group = limiter._default_limits[0]
    first_limit = next(iter(group))
    limit_str = str(first_limit.limit).lower()
    assert "60" in limit_str
    assert "minute" in limit_str


def test_key_func_is_get_remote_address() -> None:
    assert limiter._key_func is get_remote_address
