"""Validation lock: phone national-format misclassification fix (DATA-05).

Originally pinned the misclassification bug: PhoneCountryService.lookup stripped all
non-digit characters and prefix-matched raw digits, so a US national-format number
beginning with "7" (e.g. 702-555-1234, area code 702, Nevada) was misclassified to
Russia (ITU-T E.164 dialing code 7 = RU).

Wave 1 (Task 9) fixes this by requiring E.164 "+" or "00" international prefix and
returning Unknown (confidence=0.0) for bare national numbers.  This test now verifies
the CORRECT post-fix behaviour (was: assert country_code == "RU").
"""

from __future__ import annotations

from app.services.phone_country_service import PhoneCountryService


def test_national_format_number_is_unknown_after_data05_fix() -> None:
    """DATA-05 fix: bare national-format number must NOT be classified as Russia.

    "7025551234" (US area code 702, Nevada) has no '+' or '00' prefix.
    After the fix the service returns Unknown with confidence=0.0.
    """
    svc = PhoneCountryService()
    res = svc.lookup("7025551234")
    # Fixed: was "RU" (the bug); now Unknown because no international prefix supplied.
    assert res.country_code == ""
    assert res.country_name == "Unknown"
    assert res.confidence == 0.0


def test_e164_number_resolves_correctly() -> None:
    svc = PhoneCountryService()
    # +14155551234: digits "14155551234"; longest prefix wins.
    # "1415" is not in the map (that's a NANP US area code not listed for CA), so it falls
    # back to "1" -> US.
    res = svc.lookup("+14155551234")
    assert res.country_code == "US"  # prefix "1" -> ("US", "United States")
    assert res.confidence == 1.0
