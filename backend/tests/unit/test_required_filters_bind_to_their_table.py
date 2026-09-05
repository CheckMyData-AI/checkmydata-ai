"""A required filter was satisfied by the text appearing anywhere (row 2.8).

`check_required_filters` compiled a column-bound pattern and ran
`pattern.search(query)` over the **raw** SQL. Three things follow, and the audit
verified all three by executing them:

* a two-table join requiring `deleted_at IS NULL` on both tables passes when only
  one of them is filtered — nothing binds the occurrence to a table;
* the same text inside a comment or a string literal passes;
* a predicate on the wrong side of the query satisfies a requirement anyway.

Production carries 159 such predicates across 57 tables, and soft-delete column
names repeat across them — which is exactly the shape that makes an unbound match
likely rather than exotic.

**The stripping half is the session's recurring shape, for the fourth time: one
job, three implementations, one correct.** `core/safety.py` grew a dialect-aware
scanner on 2026-09-02 that blanks comments without reaching inside a string
literal or a quoted identifier. `core/sql_parser.py` has two quoting-blind
regexes doing the same job. This guard has neither and reads the raw text. The
scanner moves to a leaf both can import, and learns to blank literals too — it
already had to know where they start and end in order to avoid them.

**The binding half is bounded on purpose.** With one table in the query a bare
column is unambiguous. With more than one, the guard requires the qualified form;
and where it cannot bind the column to the table it counts the predicate
**unenforceable** rather than claiming a pass. That third state is this module's
own doctrine: the old presence-check fallback reported a check it never
performed, and a stricter guard that guesses would cost a repair loop measured at
~23 s per query.
"""

from __future__ import annotations

import pytest

from app.core.required_filter_guard import check_required_filters
from app.core.sql_text import strip_sql_comments_and_literals


def _check(query: str, required: dict[str, dict[str, str]], **kw):
    return check_required_filters(query=query, db_type="postgres", required_by_table=required, **kw)


class TestTheScrubberIsShared:
    def test_a_comment_is_blanked(self):
        out = strip_sql_comments_and_literals("SELECT 1 -- deleted_at IS NULL\n", "postgres")
        assert "deleted_at" not in out

    def test_a_string_literal_is_blanked(self):
        out = strip_sql_comments_and_literals("SELECT 'deleted_at IS NULL' AS x", "postgres")
        assert "deleted_at" not in out

    def test_real_sql_survives_intact(self):
        out = strip_sql_comments_and_literals(
            "SELECT a FROM t WHERE deleted_at IS NULL", "postgres"
        )
        assert "deleted_at IS NULL" in out

    def test_a_quoted_identifier_is_not_a_literal(self):
        """Blanking `"deleted_at"` would make a correctly-filtered query look
        unfiltered — a false block, which costs a refused answer."""
        out = strip_sql_comments_and_literals(
            'SELECT a FROM t WHERE "deleted_at" IS NULL', "postgres"
        )
        assert "deleted_at" in out

    def test_the_dialect_is_honoured(self):
        """`#` opens a comment on MySQL and is an operator on PostgreSQL — the
        distinction `safety.py` already makes, and the reason this is shared
        rather than reimplemented."""
        assert "deleted_at" not in strip_sql_comments_and_literals(
            "SELECT 1 # deleted_at IS NULL", "mysql"
        )
        assert "deleted_at" in strip_sql_comments_and_literals(
            "SELECT 1 # deleted_at IS NULL", "postgres"
        )


class TestTextOutsideTheQueryDoesNotSatisfyIt:
    def test_a_comment_does_not_satisfy_the_requirement(self):
        result = _check(
            "SELECT * FROM orders -- deleted_at IS NULL",
            {"orders": {"deleted_at": "IS NULL"}},
        )
        assert not result.is_valid

    def test_a_string_literal_does_not_satisfy_it(self):
        result = _check(
            "SELECT 'deleted_at IS NULL' AS note FROM orders",
            {"orders": {"deleted_at": "IS NULL"}},
        )
        assert not result.is_valid

    def test_a_real_predicate_still_satisfies_it(self):
        result = _check(
            "SELECT * FROM orders WHERE deleted_at IS NULL",
            {"orders": {"deleted_at": "IS NULL"}},
        )
        assert result.is_valid


class TestALiteralOperandIsNotTheSameAsAPredicateInAString:
    """The correction that four existing tests forced.

    The first fix blanked string literals before searching. That is right for
    `sql_parser`, which is looking for table names, and wrong here: a required
    predicate usually CONTAINS a literal — `status = 'active'` — so blanking made
    every such requirement unsatisfiable. Four cases in
    `test_required_filter_guard_reads_real_predicates.py` went red at once, which
    is precisely the file the repository keeps to stop unsatisfiable predicates
    reaching production.

    The distinction is positional: a match that STARTS inside a literal is text;
    a match that starts outside one may have a literal as its operand.
    """

    def test_a_predicate_whose_operand_is_a_literal_is_satisfied(self):
        result = _check(
            "SELECT * FROM posts WHERE status = 'PUBLISHED'",
            {"posts": {"status": "= 'PUBLISHED'"}},
        )
        assert result.is_valid

    def test_the_whole_predicate_inside_a_literal_is_still_not(self):
        result = _check(
            "SELECT 'status = ''PUBLISHED''' AS note FROM posts",
            {"posts": {"status": "= 'PUBLISHED'"}},
        )
        assert not result.is_valid

    def test_a_quoted_numeric_operand_survives_too(self):
        result = _check(
            "SELECT * FROM t WHERE was_handled = '1'",
            {"t": {"was_handled": "= '1'"}},
        )
        assert result.is_valid


class TestAJoinBindsEachPredicateToItsTable:
    _BOTH = {"orders": {"deleted_at": "IS NULL"}, "users": {"deleted_at": "IS NULL"}}

    def test_filtering_one_side_does_not_satisfy_the_other(self):
        """The defect, executed: one filter, two requirements, and it passed."""
        result = _check(
            "SELECT * FROM orders o JOIN users u ON u.id = o.user_id WHERE o.deleted_at IS NULL",
            self._BOTH,
        )
        assert not result.is_valid

    def test_filtering_both_sides_satisfies_both(self):
        result = _check(
            "SELECT * FROM orders o JOIN users u ON u.id = o.user_id "
            "WHERE o.deleted_at IS NULL AND u.deleted_at IS NULL",
            self._BOTH,
        )
        assert result.is_valid

    def test_the_table_name_works_as_well_as_the_alias(self):
        result = _check(
            "SELECT * FROM orders JOIN users ON users.id = orders.user_id "
            "WHERE orders.deleted_at IS NULL AND users.deleted_at IS NULL",
            self._BOTH,
        )
        assert result.is_valid

    def test_a_single_table_query_still_accepts_a_bare_column(self):
        """Binding is only needed where there is something to confuse it with.
        Requiring `orders.deleted_at` on a single-table query would false-block
        most correct SQL."""
        result = _check(
            "SELECT * FROM orders WHERE deleted_at IS NULL",
            {"orders": {"deleted_at": "IS NULL"}},
        )
        assert result.is_valid


class TestWhatItCannotBindItDoesNotClaim:
    """The module's own doctrine: the presence-check fallback it replaced
    reported a pass it had never performed."""

    def test_an_unbindable_join_is_not_reported_as_satisfied(self):
        """A bare `deleted_at IS NULL` in a two-table join could belong to
        either. It is not a pass — and it is not a hard failure either, because
        a guess in either direction is a claim the guard cannot support."""
        result = _check(
            "SELECT * FROM orders o JOIN users u ON u.id = o.user_id WHERE deleted_at IS NULL",
            {"orders": {"deleted_at": "IS NULL"}, "users": {"deleted_at": "IS NULL"}},
        )
        assert not result.is_valid, (
            "an ambiguous predicate must not be counted as satisfying two "
            "different tables' requirements"
        )


class TestTheThreeScrubbersBecameOne:
    @pytest.mark.parametrize(
        "module",
        ["app/core/safety.py", "app/core/sql_parser.py", "app/core/required_filter_guard.py"],
    )
    def test_each_uses_the_shared_scanner(self, module):
        from pathlib import Path

        assert "sql_text" in Path(module).read_text(encoding="utf-8"), (
            f"{module} must scrub SQL through the one dialect-aware scanner; three "
            "implementations of one job is how two of them stay wrong"
        )

    def test_sql_parser_no_longer_has_its_own_quoting_blind_regexes(self):
        from pathlib import Path

        src = Path("app/core/sql_parser.py").read_text(encoding="utf-8")
        assert "_STRIP_STRINGS" not in src and "_STRIP_COMMENTS" not in src
