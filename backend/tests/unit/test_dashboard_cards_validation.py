"""F-VIZ-02 — `cards_json` was stored verbatim, and a broken one renders as empty.

The row was filed as a stored-XSS vector and downgraded, correctly: React escapes its
children, so the script never executes. What was left is worse than it sounds.

`cards_json` is `JSON.stringify(DashboardCard[])` and the viewer does:

    function parseCards(json) { try { return JSON.parse(json) } catch { return [] } }

So a dashboard whose `cards_json` is malformed — or is valid JSON of the wrong shape —
**renders as an empty dashboard**. Dashboards are shared (`is_shared` defaults to `True`),
so one bad write shows everyone else a page with nothing on it and no indication that
anything is wrong. That is the same failure the demo finding was about: silence where there
should be a signal.

Validating at the write boundary is the half that can be fixed without guessing. The
contract comes from the consumer, not from imagination — `frontend/src/lib/api/types.ts:502`:

    interface DashboardCard {
      note_id: string;
      viz_config?: Record<string, unknown>;
      refresh_interval?: number;
    }

Rows written before this change are untouched: validation runs on write, so the read path
still sees whatever is already stored. Making a legacy row fail to *load* would turn a
cosmetic problem into an outage, which is the F-EXP-06 lesson pointed the other way.
"""

from __future__ import annotations

import json

import pydantic
import pytest

from app.api.routes.dashboards import DashboardCreate, DashboardUpdate


def _create(cards: object) -> DashboardCreate:
    return DashboardCreate(
        project_id="p1",
        title="t",
        cards_json=cards if isinstance(cards, str) else json.dumps(cards),
    )


class TestTheShapeTheViewerExpects:
    def test_a_list_of_cards_is_accepted(self):
        body = _create([{"note_id": "n1"}, {"note_id": "n2", "refresh_interval": 60}])

        assert body.cards_json is not None

    def test_viz_config_is_allowed_and_opaque(self):
        """The viewer treats it as `Record<string, unknown>` and hands it to the chart
        layer. Validating its interior here would be inventing a contract nobody wrote."""
        _create([{"note_id": "n1", "viz_config": {"type": "bar", "nested": {"x": [1, 2]}}}])

    def test_an_empty_list_is_a_legitimate_dashboard(self):
        _create([])

    def test_null_is_allowed(self):
        assert DashboardCreate(project_id="p1", title="t", cards_json=None).cards_json is None


class TestWhatUsedToBeStoredSilently:
    def test_malformed_json_is_refused(self):
        """This is the finding: unparseable JSON stored happily, then rendered as an empty
        dashboard for everybody the dashboard is shared with."""
        with pytest.raises(pydantic.ValidationError, match="JSON"):
            _create("{not json at all")

    @pytest.mark.parametrize("payload", ['{"note_id": "n1"}', '"a string"', "42", "null"])
    def test_a_non_list_is_refused(self, payload):
        """`parseCards` is typed `DashboardCard[]`. A bare object parses fine and then
        `cards.map` throws in the viewer, which is a blank page rather than an error."""
        with pytest.raises(pydantic.ValidationError):
            _create(payload)

    def test_a_card_without_note_id_is_refused(self):
        with pytest.raises(pydantic.ValidationError, match="note_id"):
            _create([{"viz_config": {}}])

    def test_a_note_id_that_is_not_a_string_is_refused(self):
        with pytest.raises(pydantic.ValidationError, match="note_id"):
            _create([{"note_id": 7}])

    def test_a_card_that_is_not_an_object_is_refused(self):
        with pytest.raises(pydantic.ValidationError):
            _create(["n1", "n2"])

    def test_a_non_numeric_refresh_interval_is_refused(self):
        with pytest.raises(pydantic.ValidationError, match="refresh_interval"):
            _create([{"note_id": "n1", "refresh_interval": "hourly"}])

    def test_a_viz_config_that_is_not_an_object_is_refused(self):
        with pytest.raises(pydantic.ValidationError, match="viz_config"):
            _create([{"note_id": "n1", "viz_config": [1, 2, 3]}])


class TestBoundsThatTheByteCapDoesNotGive:
    def test_too_many_cards_is_refused(self):
        """500 KB of `{"note_id":"x"}` is roughly thirty thousand cards. The byte cap
        bounds the payload and says nothing about how many notes the viewer will try to
        fetch — it issues one request per card."""
        with pytest.raises(pydantic.ValidationError, match="cards"):
            _create([{"note_id": f"n{i}"} for i in range(500)])

    def test_a_realistic_dashboard_is_not_refused(self):
        _create([{"note_id": f"n{i}"} for i in range(40)])


class TestUpdateIsGuardedToo:
    """The create/PATCH asymmetry this codebase produced five times in two days."""

    def test_update_refuses_malformed_json(self):
        with pytest.raises(pydantic.ValidationError, match="JSON"):
            DashboardUpdate(cards_json="{nope")

    def test_update_refuses_the_wrong_shape(self):
        with pytest.raises(pydantic.ValidationError, match="note_id"):
            DashboardUpdate(cards_json=json.dumps([{"viz_config": {}}]))

    def test_update_accepts_a_valid_list(self):
        assert DashboardUpdate(cards_json=json.dumps([{"note_id": "n1"}])).cards_json

    def test_update_without_cards_is_still_valid(self):
        assert DashboardUpdate(title="renamed").cards_json is None
