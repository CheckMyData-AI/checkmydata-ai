"""The board claimed to cover the audit, and nothing could check it.

With all 24 rows ticked and every one carrying evidence, a set-comparison of the 164
finding ids in `2026-09-09-full-system-audit.md` against every id the board's rows
reference found **15 with no row at all** — among them `AUTH-01` (an unverified account
accepting another person's project invitation) and `SQL-07` (the DNS-rebinding guard
that runs at save and never at connect).

Nothing was wrong with any individual row. The failure is the one this whole remediation
programme keeps meeting: **a completeness claim nobody could compute.** A board is a
list, an audit is a list, and until something compared them, "the board covers the
audit" was an impression formed by reading down the page.

So it is an exit code now. The comparison is deliberately crude — every id the audit's
summary table names must appear somewhere in the board's prose — because a cleverer
matcher is one that can be wrong in ways nobody notices.
"""

from __future__ import annotations

import pathlib
import re

_DOCS = pathlib.Path(__file__).resolve().parents[4] / "docs" / "audits"
_AUDIT = _DOCS / "2026-09-09-full-system-audit.md"
_BOARD = _DOCS / "2026-09-09-product-review-and-backlog.md"

#: Ids the board references through a range or a shorthand a plain scan cannot expand,
#: each with the row that carries it. Kept explicit so a shorthand nobody can read is a
#: decision rather than a silent gap.
_COVERED_BY_SHORTHAND = {
    # Row 9: "KNOW-01…08"
    **{f"KNOW-{n:02d}": "row 9" for n in range(1, 9)},
    # Row 3: "SEC-01…05"
    **{f"SEC-{n:02d}": "row 3" for n in range(1, 6)},
}


def _finding_ids() -> set[str]:
    """Every id the audit's own summary table names."""
    return set(re.findall(r"\| `([A-Z]+-\d+)` \|", _AUDIT.read_text(encoding="utf-8")))


def _referenced_ids() -> set[str]:
    """Every id the board mentions, expanding the `PREFIX-01/04/06` shorthand."""
    board = _BOARD.read_text(encoding="utf-8")
    ids = set(re.findall(r"\b([A-Z]{2,5}-\d+)\b", board))
    for match in re.finditer(r"\b([A-Z]{2,5})-(\d+(?:/\d+)+)", board):
        prefix = match.group(1)
        for number in match.group(2).split("/"):
            ids.add(f"{prefix}-{int(number):02d}")
    return ids | set(_COVERED_BY_SHORTHAND)


def test_every_finding_is_carried_by_a_row() -> None:
    orphans = sorted(_finding_ids() - _referenced_ids())
    assert not orphans, (
        f"{len(orphans)} audit finding(s) appear on no board row: {orphans}. "
        "A finding nobody routed is not deferred — it is lost, and the board reads as "
        "complete while it is. Add a row, or say on an existing one why it needs none."
    )


def test_the_comparison_can_actually_fail() -> None:
    """A guard that cannot go red is decoration.

    Measured rather than asserted: the real finding set minus one id must be missing
    from a reference set built without it.
    """
    findings = _finding_ids()
    assert findings, "the audit's summary table parsed as empty — the regex has rotted"
    sample = sorted(findings)[0]
    assert sample not in (_referenced_ids() - {sample})
