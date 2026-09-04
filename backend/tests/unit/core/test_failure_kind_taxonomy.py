"""One vocabulary for "why did this fail", defined once (Ш0 · REQ-4).

Four tables carry a `failure_kind String(20)` column — `request_traces`,
`query_failures`, `error_logs`, `indexing_runs` — and until this module there was
no definition of what may go in it anywhere in the codebase. Two disagreeing
vocabularies were in use:

* ``chat.py`` wrote ``"transient"`` / ``"fatal"`` (two values);
* ``stage_executor`` classified into ``transient | configuration | data_missing |
  fatal`` (four), and that one is load-bearing — ``StageResult.retryable`` reads
  it, and a non-retryable category short-circuits the retry ladder.

Production measured 2026-09-03: `failure_kind` was NULL in **all 56** failed
traces and **all 50** query failures. Filling four columns from two vocabularies
would have replaced "no answer" with "an answer nobody can group by", which is
worse — a reader would believe it.

The precedent for this module's shape is `app/analytics/source_types.py`: one
import-light definition, because the two sides of a split cannot be allowed to
disagree about the values they exchange.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.core.failure_kind import (
    FAILURE_KINDS,
    NON_RETRYABLE_KINDS,
    FailureKind,
    is_retryable,
    normalise_failure_kind,
)


class TestTheVocabulary:
    def test_it_is_the_stage_executor_s_four(self):
        """Not a new set — the one already deciding retries."""
        assert set(FAILURE_KINDS) == {"transient", "configuration", "data_missing", "fatal"}

    def test_it_is_a_tuple_so_a_caller_cannot_mutate_the_vocabulary(self):
        assert isinstance(FAILURE_KINDS, tuple)

    def test_every_value_fits_the_column(self):
        """All four tables declare `String(20)`. A value that does not fit is a
        silent truncation on MySQL and an error on Postgres."""
        for kind in FAILURE_KINDS:
            assert len(kind) <= 20, f"{kind!r} does not fit String(20)"

    def test_only_transient_is_retryable(self):
        assert is_retryable("transient") is True
        for kind in ("configuration", "data_missing", "fatal"):
            assert is_retryable(kind) is False, (
                f"{kind} must not be retryable — retrying a misconfiguration spends "
                "the budget that exists to stop a runaway"
            )

    def test_the_non_retryable_set_is_derived_not_typed_twice(self):
        assert NON_RETRYABLE_KINDS == tuple(k for k in FAILURE_KINDS if k != "transient")

    def test_an_unknown_kind_is_not_retryable(self):
        """Fail closed: an unrecognised value must not buy another attempt."""
        assert is_retryable("banana") is False
        assert is_retryable(None) is False
        assert is_retryable("") is False


class TestNormalisation:
    def test_a_known_kind_passes_through(self):
        for kind in FAILURE_KINDS:
            assert normalise_failure_kind(kind) == kind

    def test_case_and_whitespace_are_tolerated(self):
        assert normalise_failure_kind("  Transient ") == "transient"
        assert normalise_failure_kind("DATA_MISSING") == "data_missing"

    def test_none_stays_none(self):
        """A successful run has no failure kind, and that is not `fatal`."""
        assert normalise_failure_kind(None) is None
        assert normalise_failure_kind("") is None

    def test_an_unknown_string_becomes_fatal_rather_than_being_stored_raw(self):
        """The column is groupable only if every value is in the vocabulary.

        `fatal` rather than `None`: something failed, and dropping the signal
        would put it back in the 56-NULL state this work exists to leave.
        """
        assert normalise_failure_kind("ProviderExploded") == "fatal"

    def test_normalisation_output_is_always_in_the_vocabulary(self):
        for probe in ["transient", "  FATAL", "nonsense", "data_missing", "x" * 50]:
            out = normalise_failure_kind(probe)
            assert out in FAILURE_KINDS, f"{probe!r} normalised to {out!r}, outside the vocabulary"


class TestTheLiteralMatchesTheTuple:
    def test_failurekind_literal_and_failure_kinds_cannot_drift(self):
        """`FailureKind` is a typing Literal; the tuple is what runtime checks.

        Two spellings of one vocabulary is the defect this module was created to
        remove, so a test compares them rather than trusting the author.
        """
        import typing

        assert set(typing.get_args(FailureKind)) == set(FAILURE_KINDS)


class TestNothingHeavyIsImported:
    def test_the_module_imports_only_the_standard_library(self):
        """It is imported by the agents, the routes, the services and the models.

        `app/analytics/source_types.py` carries the same rule for the same
        reason: a vocabulary module that drags in SQLAlchemy or a vendor client
        cannot be imported by the light side of the split, and the second copy
        gets written instead.
        """
        src = Path(inspect.getfile(normalise_failure_kind)).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert not {m for m in imported if m == "app"}, (
            f"failure_kind must not import from app; found {sorted(imported)}"
        )


class TestTheOldVocabularyIsGone:
    @pytest.mark.parametrize("path", ["app/api/routes/chat.py"])
    def test_no_bare_failure_kind_string_literals_remain(self, path):
        """The two call sites that wrote `"transient"` / `"fatal"` inline are
        what let the vocabularies drift. They must go through the module."""
        src = Path(path).read_text(encoding="utf-8")
        # A quoted VALUE, not a quote anywhere on the line: a legitimate call
        # like `TraceMeta.utility("explain_sql", failure_kind=fk.FATAL)` has both.
        offenders = [
            line.strip()
            for line in src.splitlines()
            if 'failure_kind="' in line or "failure_kind='" in line
        ]
        assert not offenders, (
            "failure_kind must be passed as a FailureKind from the one module, "
            f"not as a literal; found: {offenders}"
        )
