"""Validation lock: phone national-format misclassification (DATA-05).

Pins the misclassification bug: PhoneCountryService.lookup strips all non-digit characters
and prefix-matches raw digits against the dialing-code map.  A national-format US number
that begins with "7" (e.g. 702-555-1234, area code 702, Nevada) has no "+" prefix, so the
service matches the leading "7" to Russia (ITU-T E.164 dialing code 7 = RU).

Wave 1 will fix this by requiring E.164 "+" notation and returning Unknown for bare national
numbers. When that fix lands, test_national_format_number_misclassified_DATA05 should be
updated (it will return "" country_code / Unknown instead of "RU").
"""

from __future__ import annotations

from app.services.phone_country_service import PhoneCountryService


def test_national_format_number_misclassified_data05() -> None:
    svc = PhoneCountryService()
    # A US national-format number "7025551234" (area code 702) has NO country prefix,
    # but current logic matches leading "7" -> Russia (dialing code 7).  Documents DATA-05.
    res = svc.lookup("7025551234")
    assert res.country_code == "RU"  # <-- the bug; Wave 1 will return Unknown for no-'+' input


def test_e164_number_resolves_correctly() -> None:
    svc = PhoneCountryService()
    # +14155551234: digits "14155551234"; longest prefix wins.
    # "1415" is not in the map (that's a NANP US area code not listed for CA), so it falls
    # back to "1" -> US.
    res = svc.lookup("+14155551234")
    assert res.country_code == "US"  # prefix "1" -> ("US", "United States")
