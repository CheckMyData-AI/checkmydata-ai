"""A table with no database side is not "db_only" — it is not a table.

Measured on production 2026-09-08: of 256 rows in `code_db_sync`, **43 named tables
absent from `db_index`**, and all 43 carried `updated_at = 2026-09-06` — every fresh run
writes them again. Twenty of those carried the status **`db_only`**, which claims *this
exists in your database and not in your code*, about tables the indexer never saw in the
database. Among them: `axios`, `vue`, `const`, `export`, `import`, `library`, `change`.
The first seven are JavaScript tokens.

The mechanism is one line, and it contradicts the docstring directly above it.
`resolve_sync_status` opens:

    has_db_side = bool((db_context or "").strip())
    if not has_db_side:
        return "code_only" if has_code_info else "db_only"

Inside the branch that has *just established there is no database side*, the `else`
returns `db_only`. The function's own stated rule is "No DB side → ``code_only``. No code
side → ``db_only``" — so the fallthrough says the opposite of the rule it implements, for
the one case where both sides are missing.

Why that case exists at all: a name extracted from source that is neither a real table
nor a described entity reaches the resolver with an empty `db_context` and no code info.
The extractor should not have produced it (that is the other half of T02), but a status
resolver must not launder a name it knows nothing about into a claim about the customer's
database. Both halves are needed: this file holds the resolver honest.
"""

from __future__ import annotations

import pytest

from app.knowledge.code_db_sync_pipeline import resolve_sync_status

#: Verbatim from production — `code_db_sync` rows whose `table_name` has no `db_index`
#: row and whose status was `db_only`. Kept as data so the regression is named, not
#: paraphrased.
PRODUCTION_PHANTOMS = [
    "axios",
    "vue",
    "const",
    "export",
    "import",
    "change",
    "library",
    "sessions",
    "workspaces",
]


class TestNoDatabaseSide:
    def test_neither_side_is_never_db_only(self) -> None:
        """The production defect, in one assertion.

        `db_only` is a claim about the database. It cannot be made about a name the
        database index has never heard of, and this branch has already established that
        it has not.
        """
        status = resolve_sync_status(
            llm_status="db_only",
            db_context="",
            has_code_info=False,
            column_mismatch_json="{}",
        )
        assert status != "db_only", (
            "a table with no database side was reported as existing in the database; "
            "this is the line that put `axios` and `vue` in the customer's code↔DB map"
        )

    @pytest.mark.parametrize("name", PRODUCTION_PHANTOMS)
    def test_the_model_cannot_talk_it_into_db_only_either(self, name: str) -> None:
        """Whatever the model answered, a missing database side settles it structurally.

        Parameterised over the real names so a future reader sees what this was about
        rather than an abstract case.
        """
        assert (
            resolve_sync_status(
                llm_status="db_only",
                db_context="",
                has_code_info=False,
                column_mismatch_json="{}",
            )
            != "db_only"
        ), name

    def test_code_side_only_is_still_code_only(self) -> None:
        """The rule that already worked must keep working."""
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="",
                has_code_info=True,
                column_mismatch_json="{}",
            )
            == "code_only"
        )

    def test_database_side_without_code_is_db_only(self) -> None:
        """And the genuine `db_only`: the database has it, the code does not.

        98 of production's rows are this, correctly — the fix must not touch them.
        """
        assert (
            resolve_sync_status(
                llm_status="matched",
                db_context="table users (id int, email text)",
                has_code_info=False,
                column_mismatch_json="{}",
            )
            == "db_only"
        )

    def test_both_sides_still_reach_the_column_arithmetic(self) -> None:
        """SYNC-L5 is untouched: both sides present, columns agree → matched."""
        assert (
            resolve_sync_status(
                llm_status="mismatch",
                db_context="table users (id int)",
                has_code_info=True,
                column_mismatch_json='{"code_only": [], "db_only": [], "matched": ["id"]}',
            )
            == "matched"
        )

    def test_the_docstring_and_the_code_agree(self) -> None:
        """The defect was a contradiction between a function and its own documentation,
        so the agreement is worth a test of its own: no branch under `not has_db_side`
        may return `db_only`, for any combination of the other inputs."""
        for has_code in (True, False):
            for llm in ("db_only", "matched", "mismatch", "code_only", "unknown"):
                for drift in ("{}", '{"code_only": [], "db_only": ["x"], "matched": []}'):
                    assert (
                        resolve_sync_status(
                            llm_status=llm,
                            db_context="   ",
                            has_code_info=has_code,
                            column_mismatch_json=drift,
                        )
                        != "db_only"
                    ), f"has_code={has_code} llm={llm} drift={drift}"


class TestThePhantomGuardStays:
    """The resolver is fixed; the guard in the write path is the belt to those braces.

    It is deliberately redundant with the fix above. The defect found on 2026-09-08 was
    one line in one resolver, and the reason it survived to production is that nothing
    downstream asked whether the row it was about to write made a claim it could support.
    A guard that only catches the bug already fixed is decoration; this one catches the
    next writer.
    """

    def test_the_claiming_statuses_are_named_once(self) -> None:
        from app.knowledge.code_db_sync_pipeline import _STATUSES_CLAIMING_A_DB_SIDE

        assert _STATUSES_CLAIMING_A_DB_SIDE == {"db_only", "matched", "mismatch"}
        # `code_only` and `unknown` make no claim about the database, so a row carrying
        # one of them is legitimate for a table the index never saw.
        assert "code_only" not in _STATUSES_CLAIMING_A_DB_SIDE
        assert "unknown" not in _STATUSES_CLAIMING_A_DB_SIDE

    def test_the_write_path_checks_membership_and_counts_refusals(self) -> None:
        """Source-level, because the write sits inside a long pipeline body that a unit
        test cannot reach without standing up an LLM, a tracker and two sessions. Reading
        the code rather than the prose, per the convention that a grep-test that trips on
        its own comment gets its comment deleted."""
        import inspect
        import re

        from app.knowledge import code_db_sync_pipeline as mod

        src = inspect.getsource(mod.CodeDbSyncPipeline.run)
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))

        assert "_STATUSES_CLAIMING_A_DB_SIDE" in code, "the guard is gone"
        assert "db_table_names" in code, "the guard has nothing to check against"
        assert "phantoms_refused" in code, "refusals must be counted, not silently dropped"
        # And the count must reach the user-visible step summary, or a run that refused
        # fifty rows reads exactly like one that refused none.
        assert "phantom" in code.lower()
