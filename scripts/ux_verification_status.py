#!/usr/bin/env python3
"""Compute what is actually known about `docs/ux/scenarios.md`, and write it into the file.

The index said `implemented` for all 127 scenarios and `PASS` for 125, and both were
read as current. They were not: **110 of the 127 carried an audit date of 2026-07-19**,
and 152 commits had landed on `main` since — including changes to user-facing behaviour.
Only 22 of 127 were referenced anywhere in code or tests, so for the other 105 there was
no anchor by which an implementation could be checked automatically at all.

"100% implemented, 98% PASS" is an assertion in that state, not a measurement. The
distinction this script draws is the one the document was missing:

* **implemented** — somebody built it. A property of the code.
* **verified** — somebody checked it, on a date, and that date has an age.

Both belong in the header, because a reader who sees only the first will believe the
second.

    python3 scripts/ux_verification_status.py            # print the block
    python3 scripts/ux_verification_status.py --write    # rewrite it in place
    python3 scripts/ux_verification_status.py --check    # exit 1 if the file disagrees
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "docs" / "ux" / "scenarios.md"

BEGIN = "<!-- verification-status:begin -->"
END = "<!-- verification-status:end -->"

#: An audit older than this is stale enough that its verdict should not be read as
#: current. Chosen against the observed failure: 110 verdicts were 35 days old and being
#: quoted as if fresh.
STALE_AFTER_DAYS = 30

_ROW = re.compile(r"^\|\s*(SCN-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|", re.M)


def rows(text: str) -> list[tuple[str, str, str]]:
    """(id, status, last-audit cell) for every index row."""
    return [(m.group(1), m.group(5).strip(), m.group(6).strip()) for m in _ROW.finditer(text)]


def anchored_ids() -> set[str]:
    """Scenario ids referenced from code or tests — the ones a machine could check."""
    out = subprocess.run(
        ["git", "grep", "-hoE", "SCN-[0-9]+", "--", "*.py", "*.ts", "*.tsx"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout
    return set(out.split())


def summarise(text: str, *, today: date, anchors: set[str]) -> dict:
    parsed = rows(text)
    verdicts: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    stale: list[str] = []
    undated: list[str] = []

    for scenario_id, _status, audit in parsed:
        found = re.search(r"(\d{4}-\d{2}-\d{2})", audit)
        verdict = re.search(r"\b(PASS|FAIL|PARTIAL)\b", audit)
        verdicts[verdict.group(1) if verdict else "no verdict"] += 1
        if not found:
            undated.append(scenario_id)
            dates["undated"] += 1
            continue
        dates[found.group(1)] += 1
        if (today - date.fromisoformat(found.group(1))).days > STALE_AFTER_DAYS:
            stale.append(scenario_id)

    return {
        "total": len(parsed),
        "statuses": Counter(s for _, s, _ in parsed),
        "verdicts": verdicts,
        "dates": dates,
        "stale": sorted(stale),
        "undated": sorted(undated),
        "anchored": sorted({i for i, _, _ in parsed} & anchors),
    }


def render(s: dict, *, today: date) -> str:
    total = s["total"]
    oldest = min((d for d in s["dates"] if d != "undated"), default=None)
    age = (today - date.fromisoformat(oldest)).days if oldest else 0
    by_date = ", ".join(f"{d} × {n}" for d, n in sorted(s["dates"].items()))
    statuses = ", ".join(f"{k} × {v}" for k, v in sorted(s["statuses"].items()))
    verdicts = ", ".join(f"{k} × {v}" for k, v in sorted(s["verdicts"].items()))

    return f"""{BEGIN}
### Implemented is not verified

Counted {today.isoformat()} — regenerate with `make ux-status`. **Every number below is
counted from the index table, never typed.**

Ages are measured against the stamp above, not against the clock. A block that aged on
its own would turn CI red on a day nobody changed anything, and a gate that fires
without a cause is one people learn to ignore. It goes stale when the *table* changes.

| | |
|---|---|
| Scenarios | **{total}** |
| Status | {statuses} |
| Last verdict | {verdicts} |
| Verified when | {by_date} |
| **Verified more than {STALE_AFTER_DAYS} days ago** | **{len(s["stale"])} of {total}** (oldest {age} days) |
| Never verified (no date) | {len(s["undated"])} |
| Referenced from code or tests | **{len(s["anchored"])} of {total}** |

*Implemented* says somebody built it. *Verified* says somebody checked it, on a date,
and that date has an age. A reader shown only the first will believe the second — which
is how "100% implemented, 98% PASS" came to be quoted while 110 of the verdicts were
five weeks old and 105 scenarios had no anchor a machine could check them by.

The stale count is a ratchet: it may fall, never rise. Re-auditing a scenario and dating
it is what moves it.
{END}"""


def current_block(text: str) -> str | None:
    if BEGIN not in text or END not in text:
        return None
    return text[text.index(BEGIN) : text.index(END) + len(END)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="rewrite the block in place")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file disagrees")
    ap.add_argument("--today", help="ISO date to compute ages against (default: now)")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    text = SCENARIOS.read_text(encoding="utf-8")
    block = render(summarise(text, today=today, anchors=anchored_ids()), today=today)

    if args.check:
        # Recompute against the stamp the file carries, so the check is a statement
        # about the table rather than about what day it is.
        stamped = re.search(rf"{re.escape(BEGIN)}\n### [^\n]*\n\nCounted (\d{{4}}-\d{{2}}-\d{{2}})", text)
        if stamped:
            today = date.fromisoformat(stamped.group(1))
            block = render(summarise(text, today=today, anchors=anchored_ids()), today=today)
        if current_block(text) == block:
            print("verification block is current")
            return 0
        print("verification block is stale — run `make ux-status`", file=sys.stderr)
        return 1

    if args.write:
        existing = current_block(text)
        if existing is not None:
            text = text.replace(existing, block, 1)
        else:
            anchor = "## Index\n"
            text = text.replace(anchor, block + "\n\n" + anchor, 1)
        SCENARIOS.write_text(text, encoding="utf-8")
        print("verification block written")
        return 0

    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
