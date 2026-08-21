"""Every closed finding on the board cites evidence. The evidence has to exist.

`docs/qa-audit/issues.md` is the project's record of what was found and what was done about
it. A struck-through row says "fixed" and points at a test file, a source line, or a
command. Nothing has ever checked that those pointers resolve.

Two kinds of drift this catches, and both happened in this session:

* **A row left open after the work shipped.** F-KNOW-08's clone cleanup reached `main` in
  #194 — `shutil.rmtree` in `indexing_artifacts.py`, ten tests in
  `test_clone_cleanup_on_delete.py` — and the row stayed open for two more iterations. It
  was noticed by accident, while reading the list for something else.
* **A row closed against a file that later moved or was renamed.** The UX scenario ratchet
  found ten of those in its own document on the same day; there is no reason this file
  would be different.

The check is deliberately narrow: a cited path must exist. It does not read the test, count
its assertions, or verify it passes — the suite does that. What it stops is a record that
claims proof and points at nothing, which is worse than a row with no citation at all,
because it reads as verified.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BOARD = REPO / "docs" / "qa-audit" / "issues.md"

#: Paths in a citation, e.g. `tests/unit/test_x.py` or `app/core/y.py:42-58`. Anchored on
#: the directories this project actually has, so prose like "the demo path" is not mistaken
#: for a file.
_PATH = re.compile(
    r"\b((?:backend/|frontend/)?(?:app|tests|src|docs|alembic)/[\w./\[\]-]+?\.(?:py|ts|tsx|md))"
)

#: A citation may name a file that has since been renamed *by design* — record why here
#: rather than deleting the citation, so the history stays readable.
ACCEPTED: dict[str, str] = {}


def _resolves(path: str) -> bool:
    """A cited path resolves from the repo root, or from backend/ or frontend/."""
    return (
        any((REPO / prefix / path).exists() for prefix in ("", "backend", "frontend"))
        or (REPO / path).exists()
    )


def _closed_rows() -> list[tuple[str, str]]:
    rows = []
    for line in BOARD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| ~~(F-[A-Z0-9]+-\w+)~~ \|", line)
        if m:
            rows.append((m.group(1), line))
    return rows


def test_the_board_has_closed_rows_to_check() -> None:
    """A regex that matches nothing passes every assertion below by vacuity, and looks
    green doing it — the same failure mode the heavy-enqueue sweep needed a guard against."""
    assert len(_closed_rows()) >= 20


def test_every_cited_path_exists() -> None:
    missing: list[str] = []
    for finding, line in _closed_rows():
        for path in _PATH.findall(line):
            if path in ACCEPTED:
                continue
            if not _resolves(path):
                missing.append(f"{finding} cites {path}")

    assert not missing, (
        "these closed findings point at files that do not exist — a record that claims "
        "proof and points at nothing reads as verified and is not:\n  " + "\n  ".join(missing)
    )


def test_the_tally_matches_the_rows_it_summarises() -> None:
    """The stated count is derived, so a drift between it and the rows means one of them
    was edited without the other. One row of drift is what surfaced a whole iteration's
    work sitting outside `main` earlier today."""
    text = BOARD.read_text(encoding="utf-8")
    open_rows = len(re.findall(r"^\| F-[A-Z]+-\d+ \|", text, re.M))
    closed_rows = len(re.findall(r"^\| ~~F-[A-Z0-9]+-\w+~~ \|", text, re.M))

    stated = re.search(r"(\d+) open rows and (\d+) struck", text)
    assert stated, (
        "the tally paragraph is gone — it is the only thing tying the summary to the rows"
    )
    assert int(stated.group(1)) == open_rows, (
        f"tally says {stated.group(1)} open rows, the file has {open_rows}"
    )
    assert int(stated.group(2)) == closed_rows, (
        f"tally says {stated.group(2)} struck through, the file has {closed_rows}"
    )
