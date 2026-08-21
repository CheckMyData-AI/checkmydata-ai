"""F-RULE-03 — `rules_to_context` had no cap, and two of five callers invented their own.

The rule text goes into an LLM prompt. It comes from files an operator drops in `rules/`
and from rows a user adds through `manage_custom_rules`, so its size is not bounded by
anything the code controls.

CLAUDE.md says rules are injected "with budget-aware truncation". Measured, that was true
at two call sites and false at three:

| site | cap |
|---|---|
| `orchestrator.py:605` | 2000 chars |
| `sql_agent.py:1991` `_load_rules_for_prompt` | 3000 chars |
| `sql_agent.py:710` the `get_custom_rules` tool | none |
| `sql_agent.py:1974` `_load_rules_for_repair` | none |
| `code_db_sync_pipeline.py:509` | none |

Two problems past the missing cap. The two numbers are unrelated magic constants, and both
cut the **tail** — so the model receives rules 1..k and cannot know that k+1..n exist.
`"... (truncated)"` says something was cut without saying what, which leaves the agent
unable to tell the user its answer may ignore rules they wrote. That is the honesty
invariant in `vision.md` §7, not a formatting preference.

The cap belongs in the one function that builds the text, so no caller can forget it, and
the notice has to be countable.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path

from app.knowledge.custom_rules import CustomRulesEngine


@dataclass
class _Rule:
    name: str
    content: str
    file_path: str = "rules/x.md"


def _rules(n: int, size: int = 100) -> list:
    return [_Rule(name=f"rule-{i}", content="x" * size) for i in range(n)]


class TestTheCapLivesInOnePlace:
    def test_a_small_rule_set_is_untouched(self):
        out = CustomRulesEngine().rules_to_context(_rules(3, 50))

        assert "rule-0" in out and "rule-2" in out
        assert "omitted" not in out

    def test_a_huge_rule_set_is_capped(self):
        out = CustomRulesEngine().rules_to_context(_rules(500, 500), max_chars=2000)

        assert len(out) < 4000, "the cap did not apply"

    def test_the_notice_says_how_many_rules_were_dropped(self):
        """`"... (truncated)"` tells the model something was cut and not what. A count is
        the difference between an agent that can say "my answer may ignore some of your
        rules" and one that cannot know."""
        out = CustomRulesEngine().rules_to_context(_rules(50, 500), max_chars=1500)

        assert "omitted" in out
        digits = [int(w) for w in out.replace("(", " ").replace(")", " ").split() if w.isdigit()]
        assert digits, f"the notice carries no count: {out[-200:]!r}"
        assert max(digits) > 0

    def test_whole_rules_are_kept_rather_than_half_of_one(self):
        """Cutting mid-rule hands the model a truncated instruction it may still follow.
        Dropping a rule whole and saying so is honest; half a rule is worse than none."""
        out = CustomRulesEngine().rules_to_context(
            [_Rule(name="keep", content="A" * 200), _Rule(name="drop", content="B" * 5000)],
            max_chars=600,
        )

        assert "keep" in out
        assert "B" * 100 not in out, "a rule was cut in half"

    def test_no_rules_still_returns_empty(self):
        assert CustomRulesEngine().rules_to_context([]) == ""

    def test_the_default_comes_from_config(self):
        from app.config import settings

        assert settings.rules_context_max_chars > 0
        out = CustomRulesEngine().rules_to_context(_rules(2000, 500))

        assert len(out) < settings.rules_context_max_chars * 2


class TestEveryCallerIsCovered:
    """The point of moving the cap into the builder: an unbounded caller becomes
    impossible rather than unlikely."""

    def test_the_builder_accepts_and_applies_a_cap(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(CustomRulesEngine.rules_to_context)))
        args = {a.arg for a in ast.walk(tree) if isinstance(a, ast.arg)}

        assert "max_chars" in args

    def test_no_caller_slices_the_result_itself(self):
        """A caller may choose a *number*; it may not implement the truncation.

        Three attempts, and each failure is worth keeping:

        1. A regex flagged `orchestrator.py` because `"(truncated)"` appears in the comment
           **explaining that the slicing was removed** — the same way
           `assert "begin_nested" not in src` failed against its own prose in the invite
           work. A string search over source cannot tell code from prose.
        2. An AST version that looked for any `text[:…]` slice or any string constant
           containing `"(truncated)"` flagged three more, including this module's own
           docstring. Comments are absent from the AST; **docstrings are not** — they are
           `ast.Constant` nodes like any other string. "Parsing removes the problem" was
           too strong a claim, and it was mine.
        3. So the check asks the exact question instead of a proxy: is the value returned
           by `rules_to_context` assigned to a name that is then **sliced** in the same
           function? No charset, no phrase, no heuristic about variable names.

        The rule is about who does the cutting: one place drops whole rules and counts
        them, and a caller that slices the joined string reintroduces both the half-rule
        and the countless notice.
        """
        import ast

        app = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []

        for f in sorted(app.rglob("*.py")):
            src = f.read_text(encoding="utf-8")
            if "rules_to_context" not in src:
                continue
            tree = ast.parse(src)
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                built: set[str] = set()
                for node in ast.walk(fn):
                    if (
                        isinstance(node, ast.Assign)
                        and isinstance(node.value, ast.Call)
                        and getattr(node.value.func, "attr", None) == "rules_to_context"
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                    ):
                        built.add(node.targets[0].id)
                if not built:
                    continue
                for node in ast.walk(fn):
                    if (
                        isinstance(node, ast.Subscript)
                        and isinstance(node.slice, ast.Slice)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in built
                    ):
                        offenders.append(f"{f.name}:{node.lineno}")

        assert not offenders, (
            f"these slice the text `rules_to_context` built: {offenders} — the builder "
            "drops whole rules and counts them; slicing undoes both"
        )


class TestOneRuleBiggerThanTheWholeBudget:
    """The case a pre-existing test caught, which my design had not considered.

    `test_rules_truncated_when_too_long` builds a single 5000-character rule and asserts
    the result is shorter. Dropping whole rules keeps that one intact, so the budget the
    cap exists to protect is blown by exactly the input the cap was written for.

    Every option is bad and they are not equally bad: keeping it whole blows the prompt,
    dropping it silently loses business logic the user wrote, and cutting it hands the
    model half an instruction. Cutting **and saying so** is the only one the agent can
    report — the same rule as everywhere else here.
    """

    def test_it_is_cut_rather_than_kept_whole(self):
        out = CustomRulesEngine().rules_to_context(
            [_Rule(name="huge", content="x" * 5000)], max_chars=800
        )

        assert len(out) < 5000

    def test_the_notice_names_the_rule_that_was_cut(self):
        out = CustomRulesEngine().rules_to_context(
            [_Rule(name="huge", content="x" * 5000)], max_chars=800
        )

        assert "huge" in out
        assert "cut short" in out

    def test_the_notice_points_at_the_setting_to_change(self):
        """A degradation the user can act on beats one they can only notice."""
        out = CustomRulesEngine().rules_to_context(
            [_Rule(name="huge", content="x" * 5000)], max_chars=800
        )

        assert "RULES_CONTEXT_MAX_CHARS" in out

    def test_a_normal_rule_after_a_huge_one_is_reported_as_omitted(self):
        out = CustomRulesEngine().rules_to_context(
            [_Rule(name="huge", content="x" * 5000), _Rule(name="small", content="y")],
            max_chars=800,
        )

        assert "cut short" in out
        assert "omitted" in out
