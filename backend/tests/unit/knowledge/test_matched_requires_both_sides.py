"""`matched` means present on both sides. It cannot be an opinion.

`sync_status` is the word a customer reads on the code↔DB screen. `matched` says *your
code and your database agree about this table*. Measured in production on 2026-08-27:

    db_index rows for  bs ls os zes active unlimit esim clones
                       interfaces price contract              →  0
    code_db_sync status for those same eleven names           →  matched, all of them

Eleven tables that **do not exist in the database** were reported as agreeing with it.

The mechanism, not a guess. `_match_tables` builds the code-only tail with
``_make_matched(nm, "", …)`` — `db_context` empty, because there is no DB side
(`code_db_sync_pipeline.py:643`). That struct goes to the LLM, which returns a
`sync_status`. The deterministic SYNC-L5 override only fires when **both** column sets are
non-empty, which a table with no DB side can never satisfy — so
``effective_status = analysis.sync_status`` stands, and the model's answer becomes the
customer's fact.

The rule that replaces it needs no model and no judgement:

* no DB side  → `code_only`
* no code side → `db_only`
* both        → the LLM may distinguish `matched` from `mismatch`, and SYNC-L5 overrides
  it when the column sets settle the question

That leaves the LLM exactly where its judgement cannot be replaced, and nowhere else.
"""

from __future__ import annotations

import json

import pytest

from app.knowledge.code_db_sync_pipeline import resolve_sync_status

#: The eleven names, verbatim from production. None had a `db_index` row; all were
#: `matched`.
CODE_ONLY_IN_PRODUCTION = [
    "bs", "ls", "os", "zes", "active", "unlimit",
    "esim", "clones", "interfaces", "price", "contract",
]

BOTH_SIDES = json.dumps({"code_only": ["a"], "db_only": [], "matched": ["b"]})
CLEAN_BOTH_SIDES = json.dumps({"code_only": [], "db_only": [], "matched": ["b"]})
ONE_SIDE = json.dumps({"code_only": [], "db_only": [], "matched": []})


class TestATableWithNoDatabaseSideIsCodeOnly:
    @pytest.mark.parametrize("name", CODE_ONLY_IN_PRODUCTION)
    def test_the_eleven_from_production(self, name: str) -> None:
        """Whatever the model said. `db_context` empty is not a matter of opinion."""
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="",
                has_code_info=True,
                column_mismatch_json=ONE_SIDE,
            )
            == "code_only"
        )

    def test_even_when_the_model_says_mismatch(self) -> None:
        """`mismatch` is as wrong as `matched` here — it also claims a DB side exists."""
        assert (
            resolve_sync_status(
                llm_status="mismatch",
                db_context="",
                has_code_info=True,
                column_mismatch_json=ONE_SIDE,
            )
            == "code_only"
        )


class TestATableWithNoCodeSideIsDbOnly:
    def test_regardless_of_the_model(self) -> None:
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="Column notes: id, name",
                has_code_info=False,
                column_mismatch_json=ONE_SIDE,
            )
            == "db_only"
        )


class TestWithBothSidesPresentNothingChanges:
    """The fix must not take judgement away where judgement is what is needed. With a DB
    side and a code side, `matched` versus `mismatch` is a real question, and SYNC-L5
    already answers it deterministically when the column sets are known."""

    def test_sync_l5_still_overrides_to_mismatch(self) -> None:
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="Column notes: id, name",
                has_code_info=True,
                column_mismatch_json=BOTH_SIDES,
            )
            == "mismatch"
        ), "a column the code has and the DB does not is a mismatch, whatever the model said"

    def test_sync_l5_still_overrides_to_matched(self) -> None:
        assert (
            resolve_sync_status(
                llm_status="mismatch",
                db_context="Column notes: id, name",
                has_code_info=True,
                column_mismatch_json=CLEAN_BOTH_SIDES,
            )
            == "matched"
        )

    def test_the_model_is_kept_when_the_columns_cannot_settle_it(self) -> None:
        """Both sides exist but one has no column information — the one case where the
        model's reading is the only reading available."""
        for said in ("matched", "mismatch"):
            assert (
                resolve_sync_status(
                    llm_status=said,
                    db_context="Column notes: id",
                    has_code_info=True,
                    column_mismatch_json=ONE_SIDE,
                )
                == said
            )


class TestItSurvivesBadInput:
    """`resolve_sync_status` runs inside the sync pipeline. Raising there loses the whole
    table's row, which is worse than keeping an uncertain status."""

    @pytest.mark.parametrize("bad", ["", "not json", "[]", "null", '{"code_only": 3}'])
    def test_unparseable_drift_falls_back_to_the_model(self, bad: str) -> None:
        out = resolve_sync_status(
            llm_status="matched",
            db_context="Column notes: id",
            has_code_info=True,
            column_mismatch_json=bad,
        )
        assert out == "matched"

    def test_a_missing_db_side_still_wins_over_bad_drift(self) -> None:
        """The side check is structural and does not depend on parsing anything."""
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="",
                has_code_info=True,
                column_mismatch_json="not json",
            )
            == "code_only"
        )

    def test_neither_side_is_not_matched(self) -> None:
        """Should not happen, and if it does, `matched` is the one answer that is
        certainly wrong."""
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="",
                has_code_info=False,
                column_mismatch_json=ONE_SIDE,
            )
            != "matched"
        )
