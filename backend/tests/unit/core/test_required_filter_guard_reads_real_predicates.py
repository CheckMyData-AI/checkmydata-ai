"""The guard could not read the predicates the system itself writes.

`code_db_sync.required_filters_json` is produced by an LLM, and the tool description
that asks for it gives this example verbatim:

    {"status": "= 1 (processed only)", "deleted_at": "IS NULL (exclude soft-deleted)"}

`_predicate_to_regex` then took everything after ``=`` — the parenthetical commentary
included — and escaped it into the pattern, producing

    was_handled\\s*=\\s*1\\ \\(processed\\ only\\)\\b

which no SQL can ever match. Measured against production on 2026-08-31: **159 predicates
configured, 1 satisfiable.** 59 compiled to patterns nothing could satisfy (57 tables
could never pass the guard); the other 98 failed the `= …` match, fell through to a bare
``\\bcol\\b`` presence check, and passed queries carrying no WHERE clause at all.

Both halves are wrong in opposite directions, and the cost of the first was measured in a
real request (trace 2e94da9c, 08-17, 358 s, timed out): every one of its eight queries
hard-failed the guard twice, paid ~23 s of LLM repair it could not possibly satisfy, and
was let through on the third attempt by the degrade rule — carrying a warning telling the
user the filters had NOT been applied. They had. The query said ``p.was_handled = 1``.

The existing suite passed throughout because every predicate in it is already clean
(``= 1``, ``IS NULL``, ``= 0``) — a shape the writer does not produce. Fixtures here
carry the prose shapes observed in production on generic table names; the schema they
came from belongs to a customer and does not belong in this repository.
"""

from __future__ import annotations

import pytest

from app.core.required_filter_guard import check_required_filters, compile_filter_check

# The three shapes that account for every production predicate.
PROSE_EQ = "= 1 (processed only)"
PROSE_NULL = "IS NULL (exclude soft-deleted)"
PROSE_GTE = ">= '2023-01-01' (exclude data before 2023)"


class TestAQuerySatisfyingEveryFilterPasses:
    """The false-block half: 57 tables could never pass."""

    @pytest.fixture
    def required(self):
        return {
            "orders": {
                "was_handled": PROSE_EQ,
                "deleted_at": PROSE_NULL,
                "created_at": PROSE_GTE,
            }
        }

    def test_first_attempt_passes_and_burns_no_repair(self, required) -> None:
        q = (
            "SELECT DATE(o.created_at) d, SUM(o.amount) rev FROM orders o "
            "WHERE o.was_handled = 1 AND o.deleted_at IS NULL "
            "AND o.created_at >= '2023-01-01' GROUP BY 1"
        )
        res = check_required_filters(q, "mysql", required, attempt=1, max_attempts=3)
        assert res.is_valid, res.error.message if res.error else "unexpected failure"

    def test_the_warning_does_not_claim_applied_filters_were_dropped(self, required) -> None:
        """A user was told totals may include soft-deleted rows while the query said
        `deleted_at IS NULL`. A false warning is worse than none: it teaches the reader
        to discount every warning the system emits."""
        q = (
            "SELECT SUM(amount) FROM orders WHERE was_handled = 1 "
            "AND deleted_at IS NULL AND created_at >= '2023-01-01'"
        )
        res = check_required_filters(q, "mysql", required, attempt=3, max_attempts=3)
        assert res.is_valid
        assert not res.warning, f"claimed a satisfied filter was dropped: {res.warning}"

    def test_a_genuinely_missing_filter_still_fails(self, required) -> None:
        """The repair must not be disabled by the fix that makes it satisfiable."""
        q = "SELECT SUM(amount) FROM orders WHERE deleted_at IS NULL"
        res = check_required_filters(q, "mysql", required, attempt=1, max_attempts=3)
        assert not res.is_valid
        assert "was_handled" in res.error.message


class TestAnUnfilteredQueryIsNotSilentlyAccepted:
    """The false-pass half: 98 predicates matched a bare column mention."""

    def test_a_select_list_mention_is_not_a_filter(self) -> None:
        required = {"users": {"created_at": PROSE_GTE}}
        res = check_required_filters(
            "SELECT created_at FROM users", "mysql", required, attempt=1, max_attempts=3
        )
        assert not res.is_valid, "a query with no WHERE clause satisfied a required filter"

    def test_soft_delete_mention_in_select_is_not_a_filter(self) -> None:
        required = {"users": {"deleted_at": PROSE_NULL}}
        res = check_required_filters(
            "SELECT id, deleted_at FROM users", "mysql", required, attempt=1, max_attempts=3
        )
        assert not res.is_valid


class TestABoundIsSatisfiedByATighterBound:
    """`created_at >= '2023-01-01'` means 'exclude pre-2023', so a six-month window
    satisfies it. Demanding the literal date would re-create the false block on every
    question that asks about a recent period — which is most of them."""

    def test_a_narrower_window_satisfies_a_lower_bound(self) -> None:
        required = {"orders": {"created_at": PROSE_GTE}}
        q = "SELECT SUM(amount) FROM orders WHERE created_at >= '2026-03-01'"
        res = check_required_filters(q, "mysql", required, attempt=1, max_attempts=3)
        assert res.is_valid, res.error.message if res.error else ""

    def test_between_satisfies_a_lower_bound(self) -> None:
        required = {"orders": {"created_at": PROSE_GTE}}
        q = "SELECT SUM(amount) FROM orders WHERE created_at BETWEEN '2026-01-01' AND '2026-06-30'"
        res = check_required_filters(q, "mysql", required, attempt=1, max_attempts=3)
        assert res.is_valid, res.error.message if res.error else ""


class TestDialectAndAliasTolerance:
    @pytest.mark.parametrize(
        "where",
        [
            "was_handled = 1",
            "o.was_handled = 1",
            "`was_handled` = 1",
            "o.`was_handled`=1",
            "was_handled = TRUE",
            "was_handled = '1'",
        ],
    )
    def test_equality_forms_all_satisfy(self, where) -> None:
        required = {"orders": {"was_handled": PROSE_EQ}}
        res = check_required_filters(
            f"SELECT 1 FROM orders o WHERE {where}", "mysql", required, attempt=1, max_attempts=3
        )
        assert res.is_valid, f"{where!r} should satisfy {PROSE_EQ!r}"

    def test_a_different_column_sharing_a_suffix_does_not_satisfy(self) -> None:
        required = {"orders": {"was_handled": PROSE_EQ}}
        res = check_required_filters(
            "SELECT 1 FROM orders WHERE prev_was_handled = 1",
            "mysql",
            required,
            attempt=1,
            max_attempts=3,
        )
        assert not res.is_valid


class TestAnUnenforceableRequirementIsNotClaimedAsChecked:
    """Some stored 'predicates' are instructions, not conditions:

        {"settings_type": "must filter by specific type for targeted configurations"}

    There is nothing to compile. The old code turned these into a bare-presence check,
    which reports a pass it never performed. Not enforcing and not claiming to is the
    only honest option; the requirement still reaches the model as prompt context."""

    PROSE_INSTRUCTION = "must filter by specific type for targeted configurations"

    def test_it_never_hard_blocks(self) -> None:
        required = {"settings": {"settings_type": self.PROSE_INSTRUCTION}}
        res = check_required_filters(
            "SELECT COUNT(*) FROM settings", "mysql", required, attempt=1, max_attempts=3
        )
        assert res.is_valid, "an uncompilable instruction must not block a query"

    def test_it_does_not_pass_by_pretending_to_check(self) -> None:
        required = {"settings": {"settings_type": self.PROSE_INSTRUCTION}}
        res = check_required_filters(
            "SELECT settings_type FROM settings", "mysql", required, attempt=1, max_attempts=3
        )
        assert res.is_valid
        assert not res.warning or "settings_type" not in (res.warning or "")


class TestNoPredicateShapeCompilesToSomethingUnsatisfiable:
    """The ratchet. A pattern containing escaped prose — `\\ \\(` — is the signature of
    the defect: it can only be satisfied by SQL that carries an English comment inside
    the predicate."""

    SHAPES = [
        ("was_handled", PROSE_EQ),
        ("deleted_at", PROSE_NULL),
        ("created_at", PROSE_GTE),
        ("status", "= 'active' (exclude inactive)"),
        ("status", "!= 'rejected' (exclude rejected requests)"),
        ("is_active", "= 1 (active only)"),
        ("updated_at", "IS NOT NULL (exclude records with NULL updated_at)"),
        ("status", "= 'PUBLISHED' (to get published posts)"),
        ("event_date", ">= 2023-01-01 (valid data only)"),
    ]

    @pytest.mark.parametrize("col,predicate", SHAPES)
    def test_the_compiled_pattern_carries_no_prose(self, col, predicate) -> None:
        pattern = compile_filter_check(col, predicate).pattern
        assert "\\ \\(" not in pattern, (
            f"{predicate!r} compiled to {pattern!r} — the commentary was escaped into the "
            "pattern, so no SQL can satisfy it"
        )

    @pytest.mark.parametrize("col,predicate", SHAPES)
    def test_every_shape_is_satisfiable_by_some_query(self, col, predicate) -> None:
        """Stronger than 'carries no prose': there must EXIST a query that passes.
        A guard nothing can satisfy is indistinguishable from a guard that always fails."""
        import re as _re

        sql_value = _re.sub(r"\s*\(.*\)\s*$", "", predicate).strip()
        candidate = f"SELECT 1 FROM t WHERE {col} {sql_value}"
        res = check_required_filters(
            candidate, "mysql", {"t": {col: predicate}}, attempt=1, max_attempts=3
        )
        assert res.is_valid, (
            f"no query satisfies {predicate!r}; the obvious candidate {candidate!r} failed"
        )
