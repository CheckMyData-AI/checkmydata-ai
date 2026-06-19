"""TLS helpers for managed Redis (Heroku ``rediss://`` uses a self-signed chain)."""

from __future__ import annotations


def redis_connect_kwargs(redis_url: str) -> dict:
    """Extra ``redis.from_url`` kwargs for providers with self-signed TLS."""
    if redis_url.startswith("rediss://"):
        # redis-py 5.x expects the string ``"none"``, not ``ssl.CERT_NONE``.
        return {"ssl_cert_reqs": "none"}
    return {}


def arq_redis_settings(redis_url: str):
    """Build ARQ ``RedisSettings`` with Heroku-compatible TLS."""
    from arq.connections import RedisSettings

    settings = RedisSettings.from_dsn(redis_url)
    if redis_url.startswith("rediss://"):
        settings.ssl_cert_reqs = "none"
        settings.ssl_check_hostname = False
    return settings
