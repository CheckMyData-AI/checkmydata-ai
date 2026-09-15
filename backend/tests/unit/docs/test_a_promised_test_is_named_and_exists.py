"""A comment that promises a test must name one, and the name must resolve.

B-05, and it is a class rather than one stale sentence. This codebase explains itself in
comments — deliberately, and it is most of what makes the history legible — so a comment
saying *"a guard test now fails if anyone does this again"* is load-bearing: it is the
only thing telling the next reader that the rule is enforced rather than hoped for.

Unnamed, that sentence is unfalsifiable. It cannot be checked, it cannot be found, and
when the test it refers to is renamed or deleted the comment keeps asserting protection
that no longer exists. Measured 2026-09-15: **13 comments promised a test, 8 named one,
5 did not** — including the one on `orchestrator.py`'s `context.extra` mutation, which
guards a defect that made `exposed_learning_ids` empty on every request the product had
ever served.

So two rules, and the second is what gives the first teeth:

1. a comment that promises a test names a `test_*.py` file;
2. that file exists.

Rule 2 is the reason this is a test rather than a convention. A name that no longer
resolves is worse than no name: it reads as a citation and is a dead link.
"""

from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[3] / "app"
TESTS = pathlib.Path(__file__).resolve().parents[2]

#: Prose that claims a test holds the rule the comment has just described.
_PROMISES = re.compile(
    r"(?:a|the)\s+(?:guard\s+|regression\s+|structural\s+|unit\s+)?test\s+"
    r"(?:now\s+)?(?:fails|catches|pins|asserts|holds|checks)",
    re.IGNORECASE,
)

#: A named test file. The `.py` is required: `test_foo` alone could be a function, and a
#: function name cannot be resolved to a file without guessing.
_NAMES = re.compile(r"test_[A-Za-z0-9_]+\.py")


def _comment_lines() -> list[tuple[pathlib.Path, int, str]]:
    """Comment and docstring lines only — a promise inside executable code is a string
    the program uses, not a claim to the reader."""
    out: list[tuple[pathlib.Path, int, str]] = []
    for path in sorted(APP.rglob("*.py")):
        in_doc = False
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.count('"""') % 2 == 1:
                in_doc = not in_doc
                out.append((path, lineno, line))
                continue
            if in_doc or stripped.startswith("#"):
                out.append((path, lineno, line))
    return out


def _promise_blocks() -> list[tuple[pathlib.Path, int, str]]:
    """A promise plus the two lines after it — the name is often on the next line."""
    lines = _comment_lines()
    by_file: dict[pathlib.Path, dict[int, str]] = {}
    for path, lineno, text in lines:
        by_file.setdefault(path, {})[lineno] = text

    blocks: list[tuple[pathlib.Path, int, str]] = []
    for path, numbered in by_file.items():
        for lineno, text in sorted(numbered.items()):
            if not _PROMISES.search(text):
                continue
            window = " ".join(
                numbered.get(n, "") for n in range(lineno - 2, lineno + 3) if n in numbered
            )
            blocks.append((path, lineno, window))
    return blocks


def test_the_walker_still_finds_promises() -> None:
    """A guard that has stopped matching passes forever — the failure this file is about,
    applied to itself."""
    assert _promise_blocks(), (
        "no comment in app/ promises a test any more. Either the convention was dropped "
        "or this pattern has stopped matching; both need a person, not a green tick."
    )


def test_every_promised_test_is_named() -> None:
    unnamed = [
        f"{path.relative_to(APP.parent)}:{lineno}"
        for path, lineno, window in _promise_blocks()
        if not _NAMES.search(window)
    ]
    assert not unnamed, (
        "these promise that a test enforces the rule they describe, without naming it — "
        "which makes the claim unfalsifiable and unfindable:\n  " + "\n  ".join(unnamed)
    )


def test_every_named_test_file_exists() -> None:
    """A name that no longer resolves reads as a citation and is a dead link.

    Scanned over EVERY comment, not only the ones still phrased as a promise — and that
    independence is the point. The first version checked names inside promise blocks, so
    naming a test removed the phrasing that made it a promise, and the reference it had
    just acquired stopped being checked. A guard whose coverage shrinks as the codebase
    complies is worse than none: it is green exactly where the work was done.
    """
    dangling: list[str] = []
    for path, lineno, text in _comment_lines():
        for name in _NAMES.findall(text):
            if not list(TESTS.rglob(name)):
                dangling.append(f"{path.relative_to(APP.parent)}:{lineno} names {name}")
    assert not dangling, (
        "these name a test file that does not exist — renamed or deleted, with the "
        "comment still asserting the protection:\n  " + "\n  ".join(dangling)
    )
