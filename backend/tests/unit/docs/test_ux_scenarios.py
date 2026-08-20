"""Consistency checks for `docs/ux/scenarios.md` (super-ux scenario-format v1).

`docs/ux/scenarios.md` is the source of truth for user-facing behavior, and it is
maintained by hand. The two mistakes that are easy to make and invisible in review are
(a) adding a `### SCN-nnn` body without the matching Index-table row, and (b) pointing
`Coverage:` at a file that does not exist (typo, rename, or a component that was never
built). Both are mechanical, so they are checked here rather than by a reviewer.

Coverage-path scope
-------------------
Paths are existence-checked from `STRICT_COVERAGE_MIN_ID` up — the scenarios added by
the analytics-sources program and everything after it. SCN-001..112 predate this check
and carry a small number of legacy entries written relative to `frontend/` instead of
`frontend/src/`; they are held at a non-growing baseline by
``test_legacy_coverage_paths_do_not_regress`` rather than mass-edited, so the debt is
recorded and cannot grow while the new work stays strictly checked.

The `planned:` marker
---------------------
A Coverage entry may be prefixed `planned:` to point at a file a later task will create.
Such an entry is not existence-checked, but it is only tolerated while the scenario is
still `draft` — see ``test_planned_coverage_is_only_used_by_draft_scenarios``.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIOS_MD = REPO_ROOT / "docs/ux/scenarios.md"
FRONTEND_SRC = REPO_ROOT / "frontend/src"

#: Coverage paths are existence-checked for scenarios with this id or higher.
STRICT_COVERAGE_MIN_ID = 113

#: Unresolvable Coverage paths inherited from the 2026-07-19 inventory sweep. All are
#: `src/__tests__/...` entries written relative to `frontend/` rather than
#: `frontend/src/`. Follow-up: normalise them, then drop this baseline to 0.
#: Pre-SCN-113 Coverage debt. **0 at 2026-08-21**, and that is the point of the number:
#: all nine entries were the same defect — a `src/__tests__/...` prefix that resolves
#: against neither `frontend/src/` nor the repo root, because the real path is
#: `frontend/src/__tests__/...`. The ratchet held them frozen for months as "legacy",
#: which is what a baseline does when nobody reads the list it is protecting.
#:
#: They were found by adding a tenth: the ratchet fired, the message printed all ten, and
#: the shared prefix was obvious in one line of output. Fixing the one that failed and
#: leaving nine identical ones beside it would have been the minimum this test asks for
#: and the wrong thing to do.
#:
#: At zero it stops being frozen debt and becomes the same rule the strict check applies
#: to SCN-113 and above: a Coverage path either resolves or it is wrong.
LEGACY_UNRESOLVED_COVERAGE_BASELINE = 0

_BODY_RE = re.compile(r"^### (SCN-(\d+)):\s*(\S.*)$")
_INDEX_ROW_RE = re.compile(r"^\|\s*(SCN-(\d+))\s*\|")
_COVERAGE_RE = re.compile(r"^- \*\*Coverage:\*\*\s*(\S.*)$")
_STATUS_RE = re.compile(r"^- \*\*Status:\*\*\s*(\S+)\s*$")
_HEADING_RE = re.compile(r"^## ")
_PLANNED_RE = re.compile(r"^\s*planned\s*:", re.IGNORECASE)
_PATH_RE = re.compile(r"[\w./()\[\]@-]+\.(?:tsx|ts|jsx|js|mjs|cjs|py|md|css|json|ya?ml)")


@dataclass
class Scenario:
    """One `### SCN-nnn` body and the fields the checks below need from it."""

    id: str
    number: int
    title: str
    status: str = ""
    coverage: str = ""

    #: Coverage entries, `;`-separated; `planned:`-prefixed ones are not existence-checked.
    entries: list[str] = field(default_factory=list)


def _read_lines() -> list[str]:
    assert SCENARIOS_MD.is_file(), f"missing scenario base: {SCENARIOS_MD}"
    return SCENARIOS_MD.read_text(encoding="utf-8").splitlines()


def _index_ids(lines: list[str]) -> list[str]:
    """Scenario ids listed in the `## Index` table, in file order (duplicates kept)."""
    ids: list[str] = []
    in_index = False
    for line in lines:
        if _HEADING_RE.match(line):
            in_index = line.strip() == "## Index"
            continue
        if in_index:
            match = _INDEX_ROW_RE.match(line)
            if match:
                ids.append(match.group(1))
    return ids


def _bodies(lines: list[str]) -> list[Scenario]:
    """One entry per `### SCN-nnn` body, in file order (duplicates kept)."""
    bodies: list[Scenario] = []
    for line in lines:
        match = _BODY_RE.match(line)
        if match:
            bodies.append(
                Scenario(
                    id=match.group(1),
                    number=int(match.group(2)),
                    title=match.group(3).strip(),
                )
            )
            continue
        if not bodies:
            continue
        status = _STATUS_RE.match(line)
        if status:
            bodies[-1].status = status.group(1)
            continue
        coverage = _COVERAGE_RE.match(line)
        if coverage:
            bodies[-1].coverage = coverage.group(1).strip()
            bodies[-1].entries = _coverage_entries(bodies[-1].coverage)
    return bodies


def _coverage_entries(coverage: str) -> list[str]:
    """Split a Coverage value into entries; `;` separates independent locations."""
    return [part.strip() for part in coverage.split(";") if part.strip()]


def _resolves(path: str) -> bool:
    """A Coverage path resolves relative to `frontend/src/` or to the repo root."""
    return (FRONTEND_SRC / path).exists() or (REPO_ROOT / path).exists()


def _unresolved_paths(scenario: Scenario) -> list[str]:
    """Path tokens in the scenario's Coverage that do not exist on disk.

    `planned:` entries are skipped, and entries with no path token at all (e.g.
    `none yet`) contribute nothing.
    """
    missing: list[str] = []
    for entry in scenario.entries:
        if _PLANNED_RE.match(entry):
            continue
        for match in _PATH_RE.finditer(entry):
            path = match.group(0)
            if not _resolves(path):
                missing.append(path)
    return missing


def test_every_body_has_exactly_one_index_row_and_vice_versa() -> None:
    lines = _read_lines()
    body_ids = {body.id for body in _bodies(lines)}
    index_ids = set(_index_ids(lines))

    body_without_index = sorted(body_ids - index_ids)
    index_without_body = sorted(index_ids - body_ids)

    assert not body_without_index and not index_without_body, (
        "docs/ux/scenarios.md is inconsistent — the Index table and the scenario "
        "bodies must describe exactly the same set of scenarios.\n"
        f"  bodies with no Index row ({len(body_without_index)}): "
        f"{body_without_index or 'none'}\n"
        f"  Index rows with no body ({len(index_without_body)}): "
        f"{index_without_body or 'none'}\n"
        f"  (bodies={len(body_ids)}, index rows={len(index_ids)})"
    )


def test_scenario_ids_are_unique() -> None:
    lines = _read_lines()
    body_ids = [body.id for body in _bodies(lines)]
    index_ids = _index_ids(lines)

    duplicate_bodies = sorted({i for i in body_ids if body_ids.count(i) > 1})
    duplicate_index = sorted({i for i in index_ids if index_ids.count(i) > 1})

    assert not duplicate_bodies, f"duplicate `### SCN-nnn` bodies: {duplicate_bodies}"
    assert not duplicate_index, f"duplicate Index rows: {duplicate_index}"


def test_every_body_has_a_status_and_a_coverage_line() -> None:
    incomplete = [
        f"{body.id} (missing: "
        + ", ".join(
            name
            for name, value in (("status", body.status), ("coverage", body.coverage))
            if not value
        )
        + ")"
        for body in _bodies(_read_lines())
        if not body.status or not body.coverage
    ]
    assert not incomplete, (
        f"every scenario body needs a `- **Status:**` and a `- **Coverage:**` line: {incomplete}"
    )


def test_new_scenario_coverage_paths_resolve() -> None:
    """Coverage paths on SCN-113+ must exist under `frontend/src/` or the repo root."""
    failures: list[str] = []
    for body in _bodies(_read_lines()):
        if body.number < STRICT_COVERAGE_MIN_ID:
            continue
        failures.extend(f"{body.id}: {path}" for path in _unresolved_paths(body))

    assert not failures, (
        "Coverage paths that do not resolve under frontend/src/ or the repo root "
        f"(checked for SCN-{STRICT_COVERAGE_MIN_ID:03d} and above): {failures}. "
        "Fix the path, or prefix the entry `planned:` if a later task creates the file."
    )


def test_planned_coverage_is_only_used_by_draft_scenarios() -> None:
    """`planned:` is an escape hatch for unbuilt files — it must not outlive `draft`."""
    offenders = [
        f"{body.id} (status={body.status})"
        for body in _bodies(_read_lines())
        if body.status != "draft" and any(_PLANNED_RE.match(entry) for entry in body.entries)
    ]
    assert not offenders, (
        "a `planned:` Coverage entry is only allowed while the scenario is `draft`; "
        f"once implemented the real path must be recorded: {offenders}"
    )


def test_legacy_coverage_paths_do_not_regress() -> None:
    """Pre-SCN-113 Coverage debt is frozen: it may shrink, never grow."""
    unresolved: list[str] = []
    for body in _bodies(_read_lines()):
        if body.number >= STRICT_COVERAGE_MIN_ID:
            continue
        unresolved.extend(f"{body.id}: {path}" for path in _unresolved_paths(body))

    assert len(unresolved) <= LEGACY_UNRESOLVED_COVERAGE_BASELINE, (
        f"legacy unresolved Coverage paths grew from "
        f"{LEGACY_UNRESOLVED_COVERAGE_BASELINE} to {len(unresolved)}: {unresolved}"
    )
