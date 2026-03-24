"""Unit tests for PhoneCountryService."""

import pytest

from app.services.phone_country_service import (
    PhoneCountryService,
    get_phone_country_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    import app.services.phone_country_service as mod

    mod._service_instance = None
    yield
    mod._service_instance = None


class TestPhoneCountryServiceLookup:
    def test_us_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+12125551234")
        assert result.country_code == "US"
        assert result.country_name == "United States"

    def test_uk_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+442071234567")
        assert result.country_code == "GB"
        assert result.country_name == "United Kingdom"

    def test_germany_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+491711234567")
        assert result.country_code == "DE"
        assert result.country_name == "Germany"

    def test_russia_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+79161234567")
        assert result.country_code == "RU"
        assert result.country_name == "Russia"

    def test_kazakhstan_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+77012345678")
        assert result.country_code == "KZ"
        assert result.country_name == "Kazakhstan"

    def test_uae_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+971501234567")
        assert result.country_code == "AE"
        assert result.country_name == "United Arab Emirates"

    def test_jamaica_nanp_number(self):
        svc = PhoneCountryService()
        result = svc.lookup("+18761234567")
        assert result.country_code == "JM"
        assert result.country_name == "Jamaica"

    def test_canada_toronto(self):
        svc = PhoneCountryService()
        result = svc.lookup("+14165551234")
        assert result.country_code == "CA"
        assert result.country_name == "Canada"

    def test_canada_montreal(self):
        svc = PhoneCountryService()
        result = svc.lookup("+15141234567")
        assert result.country_code == "CA"
        assert result.country_name == "Canada"

    def test_canada_vancouver(self):
        svc = PhoneCountryService()
        result = svc.lookup("+16041234567")
        assert result.country_code == "CA"
        assert result.country_name == "Canada"

    def test_us_vs_canada_differentiation(self):
        svc = PhoneCountryService()
        us_result = svc.lookup("+12125551234")
        ca_result = svc.lookup("+14165551234")
        assert us_result.country_code == "US"
        assert ca_result.country_code == "CA"

    def test_number_without_plus(self):
        svc = PhoneCountryService()
        result = svc.lookup("442071234567")
        assert result.country_code == "GB"

    def test_number_with_dashes(self):
        svc = PhoneCountryService()
        result = svc.lookup("+1-212-555-1234")
        assert result.country_code == "US"

    def test_number_with_spaces(self):
        svc = PhoneCountryService()
        result = svc.lookup("+49 171 1234567")
        assert result.country_code == "DE"

    def test_number_with_parentheses(self):
        svc = PhoneCountryService()
        result = svc.lookup("+1 (876) 123-4567")
        assert result.country_code == "JM"

    def test_empty_string(self):
        svc = PhoneCountryService()
        result = svc.lookup("")
        assert result.country_code == ""
        assert result.country_name == "Unknown"

    def test_none_like_empty(self):
        svc = PhoneCountryService()
        result = svc.lookup("")
        assert result.country_code == ""

    def test_non_numeric_string(self):
        svc = PhoneCountryService()
        result = svc.lookup("not a number")
        assert result.country_code == ""
        assert result.country_name == "Unknown"


class TestPhoneCountryServiceBatch:
    def test_batch_lookup(self):
        svc = PhoneCountryService()
        results = svc.lookup_batch(["+442071234567", "+491711234567", ""])
        assert len(results) == 3
        assert results[0].country_code == "GB"
        assert results[1].country_code == "DE"
        assert results[2].country_code == ""


class TestGetPhoneCountryService:
    def test_returns_singleton(self):
        s1 = get_phone_country_service()
        s2 = get_phone_country_service()
        assert s1 is s2
