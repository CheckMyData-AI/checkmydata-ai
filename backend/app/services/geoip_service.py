"""GeoIP lookup service — offline IP-to-country resolution.

Uses geoip2fast for sub-millisecond lookups from a local .dat.gz file.
The database ships with the library and requires no API keys or network calls.

Results are cached in a two-tier cache (in-memory LRU + SQLite) so repeated
lookups (within a request or across restarts) are near-instant.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.geoip_cache import GeoIPCache

logger = logging.getLogger(__name__)

_geoip_instance: GeoIP2Fast | None = None  # type: ignore[name-defined]  # noqa: F821
_init_attempted = False


@dataclass(frozen=True)
class GeoIPResult:
    country_code: str
    country_name: str
    is_private: bool = False


_UNKNOWN = GeoIPResult(country_code="", country_name="Unknown")
_PRIVATE = GeoIPResult(country_code="", country_name="Private Network", is_private=True)


def _get_geoip() -> Any | None:
    """Lazy-load the geoip2fast instance (singleton)."""
    global _geoip_instance, _init_attempted
    if _init_attempted:
        return _geoip_instance
    _init_attempted = True
    try:
        from geoip2fast import GeoIP2Fast

        _geoip_instance = GeoIP2Fast(verbose=False)
        logger.info("GeoIP2Fast loaded: %s", _geoip_instance.get_database_path())
    except Exception:
        logger.warning("geoip2fast unavailable — IP-to-country lookups will return Unknown")
        _geoip_instance = None
    return _geoip_instance


def _raw_lookup(ip: str) -> GeoIPResult:
    """Perform a raw geoip2fast lookup without cache."""
    geoip = _get_geoip()
    if geoip is None:
        return _UNKNOWN

    try:
        result = geoip.lookup(ip)
    except Exception:
        logger.debug("GeoIP lookup failed for %s", ip)
        return _UNKNOWN

    if result.is_private:
        return _PRIVATE

    cc = getattr(result, "country_code", "") or ""
    cn = getattr(result, "country_name", "") or ""
    if not cc or cc == "--":
        return _UNKNOWN

    return GeoIPResult(country_code=cc, country_name=cn)


class GeoIPService:
    """Resolves IP addresses to country codes using an offline database.

    When a ``GeoIPCache`` is provided, results are cached across both an
    in-memory LRU and a persistent SQLite store.
    """

    def __init__(self, cache: GeoIPCache | None = None) -> None:
        self._cache: GeoIPCache | None = cache

    def lookup(self, ip: str) -> GeoIPResult:
        """Look up a single IP address.

        Returns a ``GeoIPResult`` with country_code (ISO 3166-1 alpha-2)
        and country_name.  Returns empty country_code on failure.
        """
        if self._cache is not None:
            cached = self._cache.get(ip)
            if cached is not None:
                return cached

        result = _raw_lookup(ip)

        if self._cache is not None:
            self._cache.put(ip, result)

        return result

    def lookup_batch(self, ips: list[str]) -> list[GeoIPResult]:
        """Look up multiple IP addresses with deduplication and batch caching."""
        if not ips:
            return []

        if self._cache is None:
            return [_raw_lookup(ip) for ip in ips]

        unique_ips = list(dict.fromkeys(ips))

        resolved: dict[str, GeoIPResult] = self._cache.get_many(unique_ips)

        misses = [ip for ip in unique_ips if ip not in resolved]
        if misses:
            new_entries: list[tuple[str, GeoIPResult]] = []
            for ip in misses:
                result = _raw_lookup(ip)
                resolved[ip] = result
                new_entries.append((ip, result))
            self._cache.put_many(new_entries)

        return [resolved[ip] for ip in ips]


_service_instance: GeoIPService | None = None
_cache_instance: GeoIPCache | None = None


def _build_cache() -> GeoIPCache | None:
    """Create the GeoIPCache from application settings."""
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    try:
        from app.config import settings
        from app.services.geoip_cache import GeoIPCache

        if not getattr(settings, "geoip_cache_enabled", True):
            logger.info("GeoIP cache disabled by configuration")
            return None

        cache_dir = getattr(settings, "geoip_cache_dir", "./data")
        mem_size = getattr(settings, "geoip_memory_cache_size", 100_000)
        db_path = os.path.join(cache_dir, "geoip_cache.db")

        _cache_instance = GeoIPCache(db_path=db_path, memory_max_size=mem_size)
        return _cache_instance
    except Exception:
        logger.warning("Failed to initialise GeoIP cache — running without cache", exc_info=True)
        return None


def get_geoip_service() -> GeoIPService:
    """Return the module-level GeoIPService singleton."""
    global _service_instance
    if _service_instance is None:
        cache = _build_cache()
        _service_instance = GeoIPService(cache=cache)
    return _service_instance
