"""`make lint` had never run, and its failure looked like a missing tool.

`VENV` was defined as `$(BACKEND_DIR)/.venv/bin` — relative to the repository root —
while eight of the eleven recipes that use it `cd $(BACKEND_DIR)` first. A relative
path resolves AFTER that `cd`, so every one of them ran
`backend/backend/.venv/bin/<tool>`:

    $ make lint
    cd backend && backend/.venv/bin/ruff format --check app/ tests/
    /bin/sh: backend/.venv/bin/ruff: No such file or directory
    make: *** [lint] Error 127

`make lint`, `make check`, `make test`, `make test-all`, `make test-integration`,
`make migrate`, `make dev-backend` — all of them, including the command `CLAUDE.md`
documents as CI parity and the one a contributor is told to run before pushing. The
error names a path rather than a cause, and "ruff is not installed" is the obvious
reading, so the fix each time was to reach for the venv directly and the Makefile kept
its defect.

Fixed by anchoring `VENV` on `$(CURDIR)`, which is this Makefile's own directory and
therefore survives both `make -C` and an invocation from a subdirectory. This test
pins the invariant rather than the spelling: a recipe that changes directory cannot
use a path that was relative to the one it left.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[4] / "Makefile"


def _assignment(name: str) -> str:
    m = re.search(rf"^{name}\s*[:?]?=\s*(.+)$", MAKEFILE.read_text(encoding="utf-8"), re.M)
    assert m, f"the Makefile no longer defines {name}"
    return m.group(1).strip()


def test_the_venv_path_survives_a_directory_change() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    recipes = [
        line
        for line in text.splitlines()
        if line.startswith("\t") and "$(VENV)" in line and "cd $(" in line
    ]
    assert recipes, (
        "no recipe both changes directory and uses $(VENV) — either the Makefile was "
        "restructured or this walker has stopped measuring"
    )
    venv = _assignment("VENV")
    assert venv.startswith("$(CURDIR)") or venv.startswith("/"), (
        f"{len(recipes)} recipe(s) `cd` before using $(VENV), which is defined as "
        f"{venv!r} — a relative path resolves after the cd and points at "
        "backend/backend/.venv/bin, where nothing exists. Anchor it on $(CURDIR)."
    )


def test_the_venv_the_makefile_names_is_the_one_that_exists() -> None:
    """The invariant above is about shape; this one is about this checkout.

    **Skipped where the venv is absent, and the first version was wrong to refuse that.**
    Its stated reason — "a test that passes on an unset-up tree would have passed against
    the defect" — does not hold: the shape rule above catches the defect on any tree,
    because it reads the assignment rather than the filesystem. CI proved it in one run,
    where dependencies are installed into the runner's own Python and `backend/.venv`
    never exists; the test failed on a Makefile that was correct.

    So what this adds is narrow and worth keeping: on a developer machine set up the way
    `make setup` sets one up, the path the Makefile names is the venv that is there.
    """
    venv = _assignment("VENV").replace("$(CURDIR)", str(MAKEFILE.parent))
    venv = venv.replace("$(BACKEND_DIR)", _assignment("BACKEND_DIR"))
    expected = Path(MAKEFILE.parent) / _assignment("BACKEND_DIR") / ".venv"
    if not expected.exists():
        pytest.skip("no backend/.venv in this checkout — the shape rule above still applies")
    assert Path(venv).is_dir(), f"the Makefile points $(VENV) at {venv}, which is not a directory"
