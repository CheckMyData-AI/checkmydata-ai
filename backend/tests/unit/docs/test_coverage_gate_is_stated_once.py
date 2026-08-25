"""The coverage threshold lives in two files, and they have to agree.

`fail_under` in `pyproject.toml` is what a local `pytest --cov` enforces;
`--fail-under` in `.github/workflows/ci.yml` is what actually gates a merge. They are
the same policy written twice, and a number written twice eventually disagrees with
itself — which is how a developer sees green locally and red in CI, or worse, the other
way round.

`CLAUDE.md` states the same figure a third time, in prose, for a human reading the
project. That one is checked too: a document quoting a threshold that has moved is the
same defect as a board quoting a tally that has moved, and this repository spent
2026-08-25 finding four of those.

The value itself was raised 72 → 80 on 2026-08-26. It had not moved while the tracing
bug in `[tool.coverage.run]` kept the input systematically low: the combined run
measures **82%** with coverage following the greenlet (41 023 statements, 7 383 missing)
against **79%** without it. A gate ten points below reality cannot fail for any
regression anybody would plausibly ship.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PYPROJECT = REPO / "backend" / "pyproject.toml"
CI = REPO / ".github" / "workflows" / "ci.yml"
CLAUDE_MD = REPO / "CLAUDE.md"


def _declared() -> int:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["coverage"]["report"][
        "fail_under"
    ]


def _enforced() -> list[int]:
    return [int(m) for m in re.findall(r"--fail-under=(\d+)", CI.read_text(encoding="utf-8"))]


def test_the_threshold_is_declared_and_enforced() -> None:
    """Neither side may vanish: with no gate in CI the local number is advisory, and
    with no `fail_under` a local run says nothing about what will merge."""
    assert isinstance(_declared(), int)
    assert _enforced(), "no --fail-under in ci.yml — nothing gates a merge"


def test_pyproject_and_ci_agree() -> None:
    declared, enforced = _declared(), _enforced()
    assert set(enforced) == {declared}, (
        f"pyproject.toml says fail_under={declared}, ci.yml enforces {enforced}. The same "
        "policy written in two places has drifted, so a run can be green locally and red "
        "on merge — or pass a merge the project believes it would have stopped."
    )


def test_claude_md_quotes_the_same_number() -> None:
    """The prose a human reads must not contradict the gate a machine runs."""
    declared = _declared()
    text = CLAUDE_MD.read_text(encoding="utf-8")
    quoted = {int(m) for m in re.findall(r"coverage gate of (\d+)%", text)}
    quoted |= {int(m) for m in re.findall(r"`fail_under` is \*\*(\d+)%\*\*", text)}
    assert quoted, "CLAUDE.md no longer states the coverage gate at all"
    assert quoted == {declared}, (
        f"CLAUDE.md quotes {sorted(quoted)} as the coverage gate; it is {declared}"
    )
