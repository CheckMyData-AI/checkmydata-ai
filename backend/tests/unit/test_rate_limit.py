"""Unit tests for app.core.rate_limit Limiter configuration."""

from slowapi.util import get_remote_address

from app.core.rate_limit import _storage_options, limiter


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


def test_storage_options_rediss_disables_cert_verify(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.rate_limit.settings.redis_url",
        "rediss://:pass@host.example:24510/0",
    )
    assert _storage_options() == {"ssl_cert_reqs": "none"}


def test_storage_options_plain_redis_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.rate_limit.settings.redis_url",
        "redis://localhost:6379/0",
    )
    assert _storage_options() == {}
