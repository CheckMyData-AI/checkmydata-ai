"""Heroku Redis TLS helper tests."""

import pytest

from app.core.redis_tls import arq_redis_settings, redis_connect_kwargs


def test_redis_connect_kwargs_plain_redis() -> None:
    assert redis_connect_kwargs("redis://localhost:6379") == {}


def test_redis_connect_kwargs_rediss_uses_string_none() -> None:
    assert redis_connect_kwargs("rediss://:pass@host:6379") == {"ssl_cert_reqs": "none"}


def test_arq_redis_settings_rediss_disables_cert_verify() -> None:
    pytest.importorskip("arq")
    settings = arq_redis_settings("rediss://:pass@example.com:24510/0")
    assert settings.ssl is True
    assert settings.ssl_cert_reqs == "none"
    assert settings.ssl_check_hostname is False
