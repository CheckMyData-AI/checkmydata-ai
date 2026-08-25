"""No tracked file carries an unresolved git conflict marker.

`docs/qa-audit/issues.md` reached the branch behind PR #218 with three raw markers in
it — `<<<<<<< HEAD` at line 91, `=======` at 97, `>>>>>>> 979d603` at 100 — and the
tally paragraph duplicated four times underneath them, each copy claiming a different
number of open rows. Every check the repository had stayed green through it.

Two things about that are worth encoding rather than remembering:

* **A conflict marker is not a documentation problem, it is a repository problem.** The
  board is where it happened this time; the next one lands in a migration, a config
  file, or a fixture, where the numbers look plausible and nobody re-reads them. So the
  scan covers every tracked file, not `docs/`.
* **The marker survived review because nothing looked.** A human reading a 500-line
  markdown diff does not scan for `<<<<<<<`; a machine does it in 40 ms.

Only `<<<<<<< ` and `>>>>>>> ` are treated as evidence. The third marker, a bare
`=======`, is also a legal Markdown setext heading underline — and git never writes it
without the other two around it, so leaving it out costs no detection and removes the
one false positive this check could have had.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

#: `<<<<<<< ` / `>>>>>>> ` — seven characters and a space, at the start of a line. git
#: always writes a label after the space (a ref, a SHA, a description), so the trailing
#: space is part of the signature rather than an accident of formatting.
_MARKER = re.compile(r"^(?:<{7}|>{7}) ", re.M)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [REPO / name for name in out.split("\0") if name]


def test_there_are_tracked_files_to_scan() -> None:
    """A scan over an empty list passes for the wrong reason."""
    assert len(_tracked_files()) > 100


def test_no_tracked_file_has_a_conflict_marker() -> None:
    hits: list[str] = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary, or a submodule/symlink entry — nothing to read
        for match in _MARKER.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            rel = path.relative_to(REPO)
            hits.append(f"{rel}:{line_no}: {text[match.start() : match.start() + 60]!r}")

    assert not hits, (
        "unresolved git conflict markers are committed — whatever is around them was "
        "never reconciled, and every number near them is suspect:\n  " + "\n  ".join(hits)
    )


def test_the_pattern_catches_a_real_conflict_and_not_a_setext_heading() -> None:
    """The exact text that shipped on `proj/leave-and-caps`, and the Markdown it must
    not be confused with."""
    conflicted = "| Info | 12 |\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> 979d603 (wip)\n"
    assert len(_MARKER.findall(conflicted)) == 2

    setext = "Open severity tally\n=======\n\nsome prose\n"
    assert _MARKER.findall(setext) == []
