"""Nine gates that reported a check they were not performing.

P3 row 21; TEST-03, TEST-04, TEST-05, TEST-06, TEST-07, TEST-09, TEST-10, TEST-11,
TEST-13. A green gate nobody has watched fail is not evidence, and every one of these
was green over the thing it was written to catch.

- **TEST-03** — `DEPRECATED` in `exclude_lines` is a regex matched against source
  lines, and when it matches a clause header the **whole block** leaves both the
  numerator and the denominator. The other four entries are explicit coverage
  directives; this one is an ordinary English word a developer writes as
  documentation, with no idea it deletes their function from the gate.
- **TEST-04** — the guard proving "a coverage gate exists in CI" ran `re.findall` over
  the raw workflow text, comments included. Its sibling parses the same file with
  `yaml.safe_load`, so structured parsing was available and was not used.
- **TEST-05** — the guard keeping one number consistent matched exactly two phrasings,
  never opened `CONTRIBUTING.md`, and missed a third statement inside the very file it
  reads. The defect its docstring describes was present, in that file, while it was
  green.
- **TEST-06** — six smoke tests documented as running "at server boot / in CI" are run
  by neither. Nothing asserts which suites CI invokes, so deleting the integration
  step would be equally invisible.
- **TEST-07** — a test named `test_they_are_below_what_the_real_retriever_measures`
  takes the `bm25` fixture, never uses it, and asserts only that four thresholds are
  numbers between 0 and 1.
- **TEST-09** — three guards grep the whole module's source for a literal string, so
  the token satisfies them from a comment and a behaviour-preserving rename turns them
  red.
- **TEST-10** — the contrast test's `parse()` throws on `rgba(...)`, which is how two
  of the tokens it checks are declared, so their alphas were hardcoded into the test
  instead: it measures a composition the stylesheet no longer has to agree with.
- **TEST-11** — two module-level `skipif` guards left over from a dependency that
  shipped turn "the thing this file tests was deleted" into a silent skip.
- **TEST-13** — `importlib.reload(app.main)` rebinds `app.main.app` to a new FastAPI
  instance while six modules hold the old one, and the restore sits after the
  assertion, so a failure leaves the module swapped for the rest of the session.
"""

from __future__ import annotations

import ast
import pathlib
import re
import tomllib

import pytest
import yaml

_BACKEND = pathlib.Path(__file__).parents[2].parent
_ROOT = _BACKEND.parent
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _ci_run_steps() -> list[str]:
    """Every `run:` script CI actually executes, from the parsed workflow."""
    doc = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    return [
        step["run"]
        for job in doc.get("jobs", {}).values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]


class TestCoverageCountsEveryLine:
    """TEST-03."""

    def test_the_exclusion_list_holds_only_coverage_directives(self) -> None:
        config = tomllib.loads((_BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
        excluded = config["tool"]["coverage"]["report"]["exclude_lines"]

        prose = [
            line
            for line in excluded
            if not any(
                marker in line
                for marker in ("pragma", "TYPE_CHECKING", "__main__", "NotImplementedError")
            )
        ]
        assert not prose, (
            f"{prose} are matched against source lines as regexes, and a match on a "
            "clause header removes the WHOLE BLOCK from both the numerator and the "
            "denominator of the gate. Unlike the four coverage directives beside them, "
            "these are ordinary English a developer writes as documentation — with no "
            "idea it deletes their function from the measurement (TEST-03)"
        )


class TestTheCoverageGateIsExecuted:
    """TEST-04, TEST-06."""

    def test_the_gate_is_in_a_step_ci_runs(self) -> None:
        running = [s for s in _ci_run_steps() if "--fail-under" in s]
        assert running, (
            "the guard for this ran `re.findall` over the raw file, comments included, "
            "so it proved the string appears somewhere in ci.yml and not that any step "
            "executes it — while its sibling parses the same workflow with "
            "`yaml.safe_load` (TEST-04)"
        )

    def test_ci_runs_the_suite_the_readme_says_it_runs(self) -> None:
        scripts = "\n".join(_ci_run_steps())
        assert "tests/smoke" in scripts, (
            "six tests exercising the real SafetyGuard, DataGate, plan validator and "
            "router against a seeded database claim to run 'at server boot / in CI'. "
            "CI runs three explicit path lists and none includes them, and the Procfile "
            "runs alembic and uvicorn — nothing invokes pytest at boot. Only `make "
            "smoke` runs them, i.e. only when somebody remembers (TEST-06)"
        )

    @pytest.mark.parametrize("suite", ["tests/unit", "tests/integration", "tests/smoke"])
    def test_every_suite_is_named(self, suite: str) -> None:
        """Deleting a step must not be invisible."""
        assert any(suite in script for script in _ci_run_steps()), f"{suite} is not run by CI"


class TestOneNumberIsStatedOnce:
    """TEST-05."""

    def test_no_document_quotes_a_stale_coverage_number(self) -> None:
        config = tomllib.loads((_BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
        gate = int(config["tool"]["coverage"]["report"]["fail_under"])

        # A percentage whose nearby words name a GATE. Deliberately not a list of
        # blessed phrasings — that is the shape of the guard this replaces, which
        # matched two of them and missed a third in the file it was reading. And
        # deliberately not "any percentage near the word coverage", because a MEASURED
        # figure ("Backend coverage 82%") is a different claim and must be free to
        # differ from the ceiling it sits under.
        gate_words = re.compile(
            r"gate|fail[_ -]?under|enforce|must not drop|minimum|floor", re.IGNORECASE
        )
        percentage = re.compile(r"(\d{2})\s*%")
        stale: list[str] = []
        for name in ("CLAUDE.md", "CONTRIBUTING.md"):
            path = _ROOT / name
            if not path.exists():
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in percentage.finditer(line):
                    lead = line[max(0, match.start() - 60) : match.start()]
                    # Stop at the nearest sentence boundary. Without it, a sentence
                    # explaining a HISTORICAL measurement inherits the gate word from
                    # the sentence before it — which is how "The 78% previously
                    # recorded here" read as a stale gate rather than as the note
                    # explaining why the gate moved.
                    lead = lead.rsplit(". ", 1)[-1]
                    if not gate_words.search(lead):
                        continue
                    if int(match.group(1)) != gate:
                        stale.append(f"{name}:{line_no}: …{lead[-50:]}{match.group(0)}")
        assert not stale, (
            f"the gate is {gate}% and these say otherwise: {stale}. The guard that "
            "exists for this matched exactly two phrasings, never opened "
            "CONTRIBUTING.md, and missed a third statement inside the file it does "
            "read — so the defect its own docstring describes was present, there, "
            "while it was green (TEST-05)"
        )


class TestTheFloorsAreMeasuredAgainstSomething:
    """TEST-07."""

    def test_the_headroom_test_uses_its_fixture(self) -> None:
        import inspect

        from tests.unit.eval import test_real_retriever_eval as mod

        target = next(
            (
                getattr(cls, name)
                for cls in vars(mod).values()
                if isinstance(cls, type)
                for name in dir(cls)
                if name.startswith("test_") and "measures" in name
            ),
            None,
        )
        assert target is not None, "the headroom test is gone; this guard is blind"
        import textwrap

        # `cleandoc` strips the leading indentation of a DOCSTRING, not of a function
        # — reparsing its output raised a SyntaxError that read, from the outside,
        # exactly like a failure of the thing under test.
        tree = ast.parse(textwrap.dedent(inspect.getsource(target)))
        params = set(inspect.signature(target).parameters)
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        unused = sorted(params - used - {"self"})
        assert not unused, (
            f"the test takes {unused} — building a full index — and never uses it. Its "
            "four assertions establish only that each threshold is a number in (0, 1]: "
            "nothing about the retriever, nothing about headroom, and nothing about the "
            "floors being meaningful, which is exactly what its docstring says it "
            "prevents (TEST-07)"
        )


class TestNoSuiteDeletesItselfSilently:
    """TEST-11."""

    def test_no_module_level_skipif_survives_its_dependency(self) -> None:
        # A skip conditioned on whether the code under test EXISTS. An environment
        # probe (`shutil.which("git")`) is a different thing and legitimate: a missing
        # binary is a fact about the machine, not about the repository. The first
        # draft banned every module-level skipif and flagged that one — and its own
        # class, whose docstring contains the word.
        probes = re.compile(r"find_spec\s*\(\s*[\"']app\.|hasattr\s*\(\s*_?\w+\s*,")
        offenders: list[str] = []
        for path in (_BACKEND / "tests").rglob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:  # module level only
                if not isinstance(node, ast.Assign):
                    continue
                text = ast.unparse(node)
                if "skipif" in text and probes.search(text):
                    offenders.append(f"{path.relative_to(_BACKEND)}: {text[:80]}")
        assert not offenders, (
            f"{offenders} skip a whole file when a dependency is absent — and the "
            "dependencies shipped. They now turn 'the thing this file tests was "
            "deleted or renamed' into a silent skip instead of a collection error, and "
            "CI passes neither -rs nor --strict-markers, so it prints as a dot "
            "(TEST-11)"
        )


class TestNothingReloadsTheApp:
    """TEST-13."""

    def test_no_test_reloads_app_main(self) -> None:
        # The CALL, not the words: this file's own docstring names both, and a
        # substring scan flagged it.
        offenders: list[str] = []
        for path in (_BACKEND / "tests").rglob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and ast.unparse(node.func).endswith("reload")
                    and "main" in ast.unparse(node)
                ):
                    offenders.append(f"{path.relative_to(_BACKEND)}: {ast.unparse(node)[:60]}")
        assert not offenders, (
            f"{offenders} rebind `app.main.app` to a NEW FastAPI instance while six "
            "modules hold the original from collection — and `tests/integration/"
            "conftest.py` imports it lazily, so `dependency_overrides[get_db]` can land "
            "on a different object than the one a test is driving. `make check` runs "
            "unit and integration in ONE process and CI runs two, so CI never "
            "exercises the shape (TEST-13)"
        )
