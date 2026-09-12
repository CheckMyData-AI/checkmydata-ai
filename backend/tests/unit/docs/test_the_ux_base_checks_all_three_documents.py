"""The UX base is three documents and only one of them was checked.

P3 row 22; TEST-08, TEST-12, TEST-14 and BIZ-14.

- **TEST-08** — `screens.md` (SCR-01…SCR-10) and `flows.md` (FLW-01…FLW-05) were added
  on 2026-09-07, carry 26 path references between them, and have no body/index pairing
  test, no path-existence test, no status test and no verification block. SCR-01's
  Coverage names `ConnectionsPanel.tsx`, which does not exist — and `scenarios.md`
  states in prose that it was deleted.
- **TEST-12** — the row parser accepts `SCN-101a`; `anchored_ids()` two functions below
  greps `SCN-[0-9]+`, so a code reference to `SCN-101a` is captured as `SCN-101` and
  the anchor is credited to a **different scenario** while the suffixed one reports
  none. `audit_backlog`'s `stale_ids` has the same omission.
- **TEST-14** — 166 `file:line` citations are unchecked. `_PATH_RE` stops before the
  `:1511-1523`, so the line anchors are never parsed. The file's own re-audit record
  says the citations are what decays: three batches of five found **15 of 15
  behaviourally correct and 22 stale citations**. And `CLAUDE.md` states a scenario
  tally the generated block in `scenarios.md` contradicts, with nothing comparing them.
- **BIZ-14** — SCN-052's `Expected result` and its own `Errors & recovery` note
  describe opposite behaviours, and every cited line number is 40–55 lines adrift,
  while the row is stamped `implemented / PASS`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_UX = _ROOT / "docs" / "ux"
_FRONTEND = _ROOT / "frontend"

#: Every document in the UX base. The point of the list is that it is a list — the
#: guards below iterate it, so a fourth document is covered by adding one line rather
#: than by remembering to copy four tests.
_DOCUMENTS = ("scenarios.md", "screens.md", "flows.md")

#: `scenarios.md` and `screens.md` head a body with `###`; `flows.md` uses `##`.
#: The level is a formatting choice and the id is the contract, so the guard reads
#: the id — demanding one level would have failed a correct document.
_ID_RE = re.compile(r"^#{2,3} ((?:SCN|SCR|FLW)-\d+[a-z]?):")
_ROW_RE = re.compile(r"^\|\s*((?:SCN|SCR|FLW)-\d+[a-z]?)\s*\|")
#: A path, optionally followed by a line anchor: `foo.tsx:12` or `foo.tsx:12-34`.
_CITATION_RE = re.compile(
    r"([\w./()\[\]@-]+\.(?:tsx|ts|jsx|js|mjs|cjs|py|md|css|json|ya?ml))(?::(\d+)(?:-(\d+))?)?"
)


def _resolve(token: str) -> pathlib.Path | None:
    # `_UX` is in the list because the three documents legitimately cite each
    # other — a Coverage note naming `scenarios.md` is a cross-reference, and
    # resolving it is what makes the guard able to say the reference is real.
    for base in (_ROOT, _FRONTEND, _FRONTEND / "src", _ROOT / "backend", _UX):
        candidate = base / token
        if candidate.exists():
            return candidate
    return None


def _citations(document: str) -> list[tuple[str, str, int | None, int | None]]:
    """`(coverage line, path token, start, end)` for every Coverage entry."""
    path = _UX / document
    out: list[tuple[str, str, int | None, int | None]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        # Two places carry a citation: a body's `**Coverage:**` line, and the Coverage
        # column of an index row. The first draft read only the first — so putting a
        # deleted component back into SCR-01's index row passed, which is TEST-08's
        # own example arriving by the half of the document the guard could not see.
        if "**Coverage:**" not in line and not _ROW_RE.match(line):
            continue
        if re.search(r"\bplanned\s*:", line, re.IGNORECASE):
            continue
        for match in _CITATION_RE.finditer(line):
            token, start, end = match.group(1), match.group(2), match.group(3)
            out.append((line, token, int(start) if start else None, int(end) if end else None))
    return out


class TestEveryDocumentIsChecked:
    """TEST-08."""

    @pytest.mark.parametrize("document", _DOCUMENTS)
    def test_every_body_has_an_index_row(self, document: str) -> None:
        text = (_UX / document).read_text(encoding="utf-8")
        bodies = {m.group(1) for line in text.splitlines() if (m := _ID_RE.match(line))}
        rows = {m.group(1) for line in text.splitlines() if (m := _ROW_RE.match(line))}
        assert bodies, f"{document} has no bodies; this guard is blind"
        assert bodies == rows, (
            f"{document}: bodies without a row {sorted(bodies - rows)}, rows without a "
            f"body {sorted(rows - bodies)}. `scenarios.md` has had this pairing check "
            "since it was written; the other two were added on 2026-09-07 with none "
            "at all (TEST-08)"
        )

    @pytest.mark.parametrize("document", _DOCUMENTS)
    def test_every_coverage_path_resolves(self, document: str) -> None:
        missing = sorted(
            {token for _line, token, _s, _e in _citations(document) if _resolve(token) is None}
        )
        assert not missing, (
            f"{document} cites files that do not exist: {missing}. SCR-01 named "
            "`ConnectionsPanel.tsx` while `scenarios.md` states in prose that it was "
            "deleted — the two halves of the base disagreeing about the same "
            "component, with nothing comparing them (TEST-08)"
        )


class TestALineAnchorPointsAtALine:
    """TEST-14."""

    @pytest.mark.parametrize("document", _DOCUMENTS)
    def test_no_citation_points_past_the_end_of_its_file(self, document: str) -> None:
        adrift: list[str] = []
        for _line, token, start, end in _citations(document):
            if start is None:
                continue
            resolved = _resolve(token)
            if resolved is None or resolved.is_dir():
                continue
            length = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
            if start > length or (end is not None and end > length):
                adrift.append(f"{token}:{start}{f'-{end}' if end else ''} (file has {length})")
        assert not adrift, (
            f"{document}: {adrift}. 166 citations in the base are unchecked because "
            "`_PATH_RE` stops before the `:1511-1523`, and the file's own re-audit "
            "record says the citations are what decays — three batches of five found "
            "15 of 15 behaviourally correct and 22 stale citations (TEST-14)"
        )

    def test_the_documented_tally_matches_the_generated_one(self) -> None:
        block = (_UX / "scenarios.md").read_text(encoding="utf-8")
        bodies = [m.group(1) for line in block.splitlines() if (m := _ID_RE.match(line))]

        claude = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        # Tolerant of emphasis around the number: the figure it reads is stated with
        # `**` in the document, and a guard that only matched the bare digits reported
        # "no count stated" — a false absence, which is worse than a false mismatch
        # because it reads as the guard having nothing to check.
        claimed = re.search(r"\(\**(\d+)\s+scenarios;", claude)
        assert claimed is not None, "CLAUDE.md no longer states a scenario count"
        assert int(claimed.group(1)) == len(bodies), (
            f"CLAUDE.md says {claimed.group(1)} scenarios and the base has "
            f"{len(bodies)}. Nothing compared the two, which is the same shape as a "
            "board quoting a tally that has moved (TEST-14)"
        )


class TestASuffixedIdIsCountedAsItself:
    """TEST-12."""

    def test_the_anchor_grep_accepts_a_suffix(self) -> None:
        import inspect
        import sys

        sys.path.insert(0, str(_ROOT / "scripts"))
        import ux_verification_status as status  # noqa: PLC0415

        for name in ("anchored_ids", "audit_backlog"):
            source = inspect.getsource(getattr(status, name))
            assert "SCN-[0-9]+\\b" not in source and 'SCN-[0-9]+"' not in source, (
                f"{name} greps `SCN-[0-9]+`, so a code reference to SCN-101a is "
                "captured as SCN-101 — the anchor is credited to a DIFFERENT scenario "
                "and the suffixed one reports none. The row parser two functions up "
                "was widened for exactly this and these were not (TEST-12)"
            )

    def test_a_suffixed_reference_is_attributed_to_itself(self) -> None:
        import sys

        sys.path.insert(0, str(_ROOT / "scripts"))
        import ux_verification_status as status  # noqa: PLC0415

        pattern = getattr(status, "SCENARIO_ID_RE", None)
        assert pattern is not None, (
            "the id shape is spelled inline in three places rather than named once, "
            "which is how two of them missed the suffix"
        )
        assert pattern.findall("see SCN-101a and SCN-102") == ["SCN-101a", "SCN-102"]


class TestScenario052SaysOneThing:
    """BIZ-14."""

    def test_its_expected_result_and_its_gap_note_agree(self) -> None:
        text = (_UX / "scenarios.md").read_text(encoding="utf-8")
        body = text.split("### SCN-052:", 1)
        assert len(body) == 2, "SCN-052 is gone; this guard is blind"
        section = body[1].split("\n### ", 1)[0]

        expected = re.search(r"\*\*Expected result:\*\*\s*(.+)", section)
        assert expected is not None, "SCN-052 has no Expected result"
        gap = "GAP:" in section

        assert not gap or "canned" in expected.group(1).lower(), (
            "the Expected result and the `Errors & recovery` note describe opposite "
            "behaviours — one says the WrongDataModal investigation flow runs, the "
            "other says thumbs-down sends a canned prompt instead. A reader taking the "
            f"Expected result as the contract gets the opposite of what ships: "
            f"{expected.group(1)[:120]} (BIZ-14)"
        )
