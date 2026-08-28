"""Two migrations must not claim the same revision id.

Alembic keys its graph on `revision`, so a duplicate does not collide loudly — it
makes the graph ambiguous, and what surfaces is a cycle several commands later:

    alembic.script.revision.CycleDetected: Cycle is detected in revisions
    (6287a47828ca, b1c2d3e4f5a6, c2d3e4f5a6b7, d3e4f5a6b7c8)

Hit on 2026-08-28 while adding `doc_embeddings`: `b1c2d3e4f5a6` was already taken by
`b1c2d3e4f5a6_batch_started_at_claim.py`. The message names four revisions and not
the duplicate, and it appears only when something walks the graph — so a migration
authored with a taken id can be committed, reviewed and merged before anything
notices. This project's ids are hand-picked hex strings rather than the ones
`alembic revision` generates, which is what puts the collision within reach.

Read with `ast` rather than a regex, and that is not fastidiousness. The first
version of this file used a regex for `down_revision` and reported **seven** heads
where alembic reports one, because this repository has merge migrations whose parent
is a tuple — ``down_revision = ("a2b3c4d5e6f7", "g4h5i6j7k8l9")``. A test that
misreads the graph is worse than no test: it fails on a healthy repository, and the
lesson taken is to delete the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _assignments(path: Path) -> dict[str, object]:
    """Read module-level `revision` / `down_revision` literals, annotated or not."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        else:
            continue
        if value is None:
            continue
        for name in names:
            if name in ("revision", "down_revision"):
                try:
                    out[name] = ast.literal_eval(value)
                except ValueError:  # a computed value — not something to guess at
                    pass
    return out


def _graph() -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Return ``({revision: [files]}, {revision: {parents}})``."""
    revisions: dict[str, list[str]] = {}
    parents: dict[str, set[str]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        found = _assignments(path)
        rev = found.get("revision")
        if not isinstance(rev, str):
            continue
        revisions.setdefault(rev, []).append(path.name)
        down = found.get("down_revision")
        if isinstance(down, str):
            parents[rev] = {down}
        elif isinstance(down, (tuple, list)):
            parents[rev] = {d for d in down if isinstance(d, str)}
        else:
            parents[rev] = set()
    return revisions, parents


def test_every_revision_id_is_claimed_once() -> None:
    revisions, _ = _graph()
    duplicates = {rev: files for rev, files in revisions.items() if len(files) > 1}
    assert not duplicates, f"revision ids claimed by more than one migration: {duplicates}"


def test_there_is_exactly_one_head() -> None:
    """A head is a revision nothing names as a parent. Two of them is a branch someone
    has to merge, and `alembic upgrade head` refuses until they do — at release time,
    on the dyno, before uvicorn starts."""
    revisions, parents = _graph()
    named_as_parent = {p for ps in parents.values() for p in ps}
    heads = sorted(set(revisions) - named_as_parent)
    assert len(heads) == 1, f"expected one head, found {heads}"


def test_every_parent_exists() -> None:
    """A dangling parent is the third way this graph breaks, and it reads as a missing
    file rather than as the typo in an id that it usually is."""
    revisions, parents = _graph()
    dangling = {
        rev: sorted(p for p in ps if p not in revisions) for rev, ps in parents.items() if ps
    }
    dangling = {rev: missing for rev, missing in dangling.items() if missing}
    assert not dangling, f"down_revision names a revision that does not exist: {dangling}"


def test_the_reader_sees_the_merge_migrations() -> None:
    """The guard on the guard. If `_graph` ever stops understanding a tuple parent, the
    head count silently inflates and this file starts failing on a healthy repository —
    which is how a correct test gets deleted. Assert that at least one merge migration
    is parsed with more than one parent, so that regression fails *here*, naming itself.
    """
    _, parents = _graph()
    merges = {rev: ps for rev, ps in parents.items() if len(ps) > 1}
    assert merges, "no multi-parent migration parsed — the tuple form is being missed"
