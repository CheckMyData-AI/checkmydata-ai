"""A tracked symlink must point inside the repository, by a relative path.

On 2026-09-26 #432 committed `frontend/node_modules` as a symlink to an absolute path
on the author's machine: a worktree had borrowed the main checkout's `node_modules`,
and `.gitignore`'s `node_modules/` — with the trailing slash — matches directories
only, so the link was not ignored and `git add -A` took it. Every other checkout got a
link to a path that does not exist there.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]


def _tracked_symlinks() -> list[tuple[str, str]]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-s"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    links = []
    for line in out.splitlines():
        mode, _sha, _stage, path = line.split(maxsplit=3)
        if mode == "120000":
            target = os.readlink(REPO / path) if (REPO / path).is_symlink() else ""
            links.append((path, target))
    return links


def test_no_tracked_symlink_points_outside_the_repository() -> None:
    bad = []
    for path, target in _tracked_symlinks():
        if not target:
            continue
        resolved = (REPO / path).parent.joinpath(target).resolve()
        if os.path.isabs(target) or REPO.resolve() not in resolved.parents:
            bad.append(f"{path} -> {target}")
    assert not bad, f"tracked symlinks leave the repository: {bad}"


def test_node_modules_is_ignored_as_a_symlink_too() -> None:
    """`node_modules/` ignores a directory only; a link named `node_modules` slips past."""
    res = subprocess.run(
        # A path that does not exist is judged as a FILE — which is what a symlink is to
        # git — so a directory-only pattern cannot pass this by accident.
        ["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", "no-such-dir/node_modules"],
        capture_output=True,
    )
    if res.returncode not in (0, 1):
        pytest.skip("git check-ignore unavailable")
    assert res.returncode == 0, "frontend/node_modules is not ignored when it is a file or link"
