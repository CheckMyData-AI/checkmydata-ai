#!/usr/bin/env python3
"""Fail when a board row that was `done` on main comes back `todo`.

Written after doing it twice in one day. `docs/AUDIT_REMEDIATION_2026-09.md` is a
single dense table that every branch edits, so parallel work always collides
there — four conflicts in one session. The resolution is always the same (take
main's version, re-apply this branch's rows), and the failure mode is always the
same too: re-applying from memory silently reverts a row somebody else closed.

The working rules already said so. A rule in a document did not stop its own
author, twice, because a reverted row looks like nothing in a diff full of prose.
This is the mechanical version: it compares statuses, not text.

    python3 scripts/board_no_regression.py [base-ref]

Exit 1 and name every row whose status went backwards.
"""

from __future__ import annotations

import re
import subprocess
import sys

BOARD = "docs/AUDIT_REMEDIATION_2026-09.md"
ROW = re.compile(r"^\|\s*(\d+\.\d+)\s*\|[^|]*\|[^|]*\|\s*([^|]*?)\s*\|", re.M)
CLOSED = ("done", "shipped")


def _statuses(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).lower() for m in ROW.finditer(text)}


def main(base: str = "origin/main") -> int:
    try:
        before = subprocess.run(
            ["git", "show", f"{base}:{BOARD}"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:  # pragma: no cover - env issue
        print(f"cannot read {BOARD} at {base}: {exc}", file=sys.stderr)
        return 2

    with open(BOARD, encoding="utf-8") as fh:
        after = _statuses(fh.read())
    old = _statuses(before)

    regressed = [
        row
        for row, status in old.items()
        if status.startswith(CLOSED)
        and row in after
        and not after[row].startswith(CLOSED)
    ]
    dropped = [row for row, status in old.items() if status.startswith(CLOSED) and row not in after]

    for row in sorted(regressed, key=lambda r: [int(p) for p in r.split(".")]):
        print(f"REGRESSED  row {row}: '{old[row]}' on {base} -> '{after[row]}' here")
    for row in sorted(dropped, key=lambda r: [int(p) for p in r.split(".")]):
        print(f"DROPPED    row {row}: was '{old[row]}' on {base}, absent here")

    if regressed or dropped:
        print(
            f"\n{len(regressed) + len(dropped)} row(s) went backwards. A conflict "
            "resolution re-applied from memory rather than from the base is how a "
            "closed row silently reopens.",
            file=sys.stderr,
        )
        return 1
    print(f"board OK: {len(old)} rows on {base}, none regressed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
