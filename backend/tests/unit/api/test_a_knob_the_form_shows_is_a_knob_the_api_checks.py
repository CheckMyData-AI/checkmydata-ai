"""A-08 (and A-04's half of it): the GA4 form's knobs are checked where they are written.

The connection form owned two keys — the first property id and the backfill window —
and `source_config` reached the database as a free-form dict. Three consequences, all
of them visible only at 03:00 in the collector's log:

* `event_names` and `currency_code` were documented, read by the adapter, and settable
  by nobody: `GA4Config`'s docstring said the UI "nudges users to name the ones they
  care about" while the form had no such field, so every GA4 connection collected every
  event on the property.
* `currency_code` typed by hand as "dollars" is a 400 from GA4 — *invalid-request* in
  the taxonomy, which is never retried — on every period of every night.
* `property_timezone` (A-04) that resolves to nothing falls back to the scheduler's
  clock, which is the defect the knob exists to close, and does it silently.

The window is clamped because there is a nearest legal value; these two are refused
because there is not. Both are checked by the same helpers the collector's own config
parser uses, so an API call cannot store a document the collector will not accept.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analytics.source_types import validated_currency_code, validated_timezone
from app.api.routes.connections import ConnectionCreate, ConnectionUpdate


def _update(**config: object) -> dict[str, object] | None:
    return ConnectionUpdate(source_config=dict(config)).source_config


class TestTheHelpers:
    def test_a_zone_is_kept_verbatim(self):
        assert validated_timezone(" America/Los_Angeles ") == "America/Los_Angeles"

    def test_an_absent_zone_is_none(self):
        assert validated_timezone(None) is None
        assert validated_timezone("  ") is None

    @pytest.mark.parametrize("bad", ["PST", "UTC+2", "Middle/Earth", "-08:00"])
    def test_a_zone_that_names_no_place_is_refused(self, bad: str):
        with pytest.raises(ValueError, match="IANA"):
            validated_timezone(bad)

    def test_a_currency_is_upper_cased(self):
        assert validated_currency_code("usd") == "USD"

    @pytest.mark.parametrize("bad", ["dollars", "US", "US$", "1234"])
    def test_a_currency_that_is_not_a_code_is_refused(self, bad: str):
        with pytest.raises(ValueError, match="ISO-4217"):
            validated_currency_code(bad)


class TestTheApiBoundary:
    """The React form is not a validator: a direct API call never runs it."""

    def test_the_update_route_refuses_an_unresolvable_zone(self):
        with pytest.raises(ValidationError, match="IANA"):
            _update(property_timezone="PST")

    def test_the_update_route_refuses_a_currency_the_vendor_cannot_parse(self):
        with pytest.raises(ValidationError, match="ISO-4217"):
            _update(currency_code="dollars")

    def test_the_create_route_refuses_it_too(self):
        with pytest.raises(ValidationError, match="IANA"):
            ConnectionCreate(
                project_id="p",
                name="ga4",
                source_type="ga4",
                vendor_credential_id="cred-1",
                source_config={"property_ids": ["1"], "property_timezone": "Mars/Olympus"},
            )

    def test_a_good_document_is_normalised_rather_than_merely_allowed(self):
        config = _update(
            property_ids=["1", "2"],
            currency_code=" eur ",
            property_timezone=" Europe/Berlin ",
            event_names=["purchase"],
        )

        assert config == {
            "property_ids": ["1", "2"],
            "currency_code": "EUR",
            "property_timezone": "Europe/Berlin",
            "event_names": ["purchase"],
        }

    def test_the_window_is_still_clamped_rather_than_refused(self):
        """The two rules coexist: a number has a nearest legal value, a zone does not."""
        assert _update(backfill_days=100_000) == {"backfill_days": 3650}

    def test_a_key_this_does_not_understand_is_left_alone(self):
        assert _update(something_a_later_vendor_adds="x") == {"something_a_later_vendor_adds": "x"}


class TestTheCollectorAcceptsWhatTheApiStored:
    """The one property that makes the pair worth sharing a helper."""

    def test_a_config_the_api_accepted_parses(self):
        from app.analytics.ga4.config import GA4Config

        stored = _update(
            property_ids=["294380179"],
            currency_code="usd",
            property_timezone="America/Los_Angeles",
            event_names=["purchase", " sign_up "],
        )
        assert stored is not None

        config = GA4Config.from_mapping(stored)

        assert config.currency_code == "USD"
        assert config.property_timezone == "America/Los_Angeles"
        assert config.event_names == ("purchase", "sign_up")
