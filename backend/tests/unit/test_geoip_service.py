"""Unit tests for GeoIPService."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.geoip_cache import GeoIPCache
from app.services.geoip_service import GeoIPResult, GeoIPService


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import app.services.geoip_service as mod

    mod._geoip_instance = None
    mod._init_attempted = False
    mod._service_instance = None
    mod._cache_instance = None
    yield
    mod._geoip_instance = None
    mod._init_attempted = False
    mod._service_instance = None
    mod._cache_instance = None


class TestGeoIPResult:
    def test_frozen_dataclass(self):
        r = GeoIPResult(country_code="US", country_name="United States")
        assert r.country_code == "US"
        assert r.country_name == "United States"
        assert r.is_private is False

    def test_private_flag(self):
        r = GeoIPResult(country_code="", country_name="Private", is_private=True)
        assert r.is_private is True


class TestGeoIPServiceLookup:
    def test_lookup_valid_ip(self):
        svc = GeoIPService()
        mock_geoip = MagicMock()
        mock_result = MagicMock()
        mock_result.country_code = "DE"
        mock_result.country_name = "Germany"
        mock_result.is_private = False
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("8.8.8.8")

        assert result.country_code == "DE"
        assert result.country_name == "Germany"
        assert result.is_private is False

    def test_lookup_private_ip(self):
        svc = GeoIPService()
        mock_geoip = MagicMock()
        mock_result = MagicMock()
        mock_result.is_private = True
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("192.168.1.1")

        assert result.is_private is True
        assert result.country_code == ""
        assert result.country_name == "Private Network"

    def test_lookup_unknown_ip(self):
        svc = GeoIPService()
        mock_geoip = MagicMock()
        mock_result = MagicMock()
        mock_result.is_private = False
        mock_result.country_code = "--"
        mock_result.country_name = ""
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("0.0.0.0")

        assert result.country_code == ""
        assert result.country_name == "Unknown"

    def test_lookup_exception(self):
        svc = GeoIPService()
        mock_geoip = MagicMock()
        mock_geoip.lookup.side_effect = RuntimeError("bad ip")

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("not-an-ip")

        assert result.country_code == ""
        assert result.country_name == "Unknown"

    def test_lookup_no_geoip_available(self):
        svc = GeoIPService()

        with patch("app.services.geoip_service._get_geoip", return_value=None):
            result = svc.lookup("8.8.8.8")

        assert result.country_code == ""
        assert result.country_name == "Unknown"


class TestGeoIPServiceBatch:
    def test_lookup_batch(self):
        svc = GeoIPService()
        mock_geoip = MagicMock()

        results_map = {
            "1.1.1.1": MagicMock(country_code="AU", country_name="Australia", is_private=False),
            "8.8.8.8": MagicMock(country_code="US", country_name="United States", is_private=False),
        }
        mock_geoip.lookup.side_effect = lambda ip: results_map[ip]

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            batch = svc.lookup_batch(["1.1.1.1", "8.8.8.8"])

        assert len(batch) == 2
        assert batch[0].country_code == "AU"
        assert batch[1].country_code == "US"

    def test_lookup_batch_empty(self):
        svc = GeoIPService()
        assert svc.lookup_batch([]) == []


class TestGetGeoIPService:
    def test_returns_singleton(self):
        from app.services.geoip_service import get_geoip_service

        s1 = get_geoip_service()
        s2 = get_geoip_service()
        assert s1 is s2


# ------------------------------------------------------------------
# Cache integration tests
# ------------------------------------------------------------------


@pytest.fixture()
def cache(tmp_path):
    db = os.path.join(str(tmp_path), "test_geoip.db")
    c = GeoIPCache(db_path=db, memory_max_size=1000)
    yield c
    c.close()


class TestCacheIntegration:
    """Tests that GeoIPService correctly reads from and writes to cache."""

    def test_lookup_populates_cache(self, cache: GeoIPCache):
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        mock_result = MagicMock(country_code="DE", country_name="Germany", is_private=False)
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("8.8.8.8")

        assert result.country_code == "DE"
        assert cache.get("8.8.8.8") is not None
        assert cache.get("8.8.8.8").country_code == "DE"

    def test_lookup_serves_from_cache(self, cache: GeoIPCache):
        cache.put("8.8.8.8", GeoIPResult(country_code="US", country_name="United States"))
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            result = svc.lookup("8.8.8.8")

        assert result.country_code == "US"
        mock_geoip.lookup.assert_not_called()

    def test_lookup_miss_then_hit(self, cache: GeoIPCache):
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        mock_result = MagicMock(country_code="JP", country_name="Japan", is_private=False)
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            r1 = svc.lookup("1.2.3.4")
            r2 = svc.lookup("1.2.3.4")

        assert r1.country_code == "JP"
        assert r2.country_code == "JP"
        assert mock_geoip.lookup.call_count == 1


class TestBatchCacheIntegration:
    """Tests that lookup_batch deduplicates and caches correctly."""

    def test_batch_deduplication(self, cache: GeoIPCache):
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        mock_result = MagicMock(country_code="US", country_name="United States", is_private=False)
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            results = svc.lookup_batch(["8.8.8.8", "8.8.8.8", "8.8.8.8"])

        assert len(results) == 3
        assert all(r.country_code == "US" for r in results)
        assert mock_geoip.lookup.call_count == 1

    def test_batch_partial_cache_hit(self, cache: GeoIPCache):
        cache.put("1.1.1.1", GeoIPResult(country_code="AU", country_name="Australia"))

        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        mock_result = MagicMock(country_code="US", country_name="United States", is_private=False)
        mock_geoip.lookup.return_value = mock_result

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            results = svc.lookup_batch(["1.1.1.1", "8.8.8.8"])

        assert results[0].country_code == "AU"
        assert results[1].country_code == "US"
        assert mock_geoip.lookup.call_count == 1

    def test_batch_populates_cache(self, cache: GeoIPCache):
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        lookup_map = {
            "1.1.1.1": MagicMock(country_code="AU", country_name="Australia", is_private=False),
            "8.8.8.8": MagicMock(country_code="US", country_name="United States", is_private=False),
        }
        mock_geoip.lookup.side_effect = lambda ip: lookup_map[ip]

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            svc.lookup_batch(["1.1.1.1", "8.8.8.8"])

        assert cache.get("1.1.1.1").country_code == "AU"
        assert cache.get("8.8.8.8").country_code == "US"

    def test_batch_preserves_order(self, cache: GeoIPCache):
        svc = GeoIPService(cache=cache)
        mock_geoip = MagicMock()
        lookup_map = {
            "1.1.1.1": MagicMock(country_code="AU", country_name="Australia", is_private=False),
            "8.8.8.8": MagicMock(country_code="US", country_name="United States", is_private=False),
            "5.5.5.5": MagicMock(country_code="DE", country_name="Germany", is_private=False),
        }
        mock_geoip.lookup.side_effect = lambda ip: lookup_map[ip]

        with patch("app.services.geoip_service._get_geoip", return_value=mock_geoip):
            results = svc.lookup_batch(["5.5.5.5", "1.1.1.1", "8.8.8.8", "1.1.1.1"])

        assert [r.country_code for r in results] == ["DE", "AU", "US", "AU"]
