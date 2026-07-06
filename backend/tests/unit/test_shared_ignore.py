"""Unit tests for the shared ignore set (CODEIDX-C9)."""

from __future__ import annotations

from app.knowledge.shared_ignore import SKIP_DIRS, is_ignored_path


def test_test_and_generated_dirs_ignored() -> None:
    assert is_ignored_path("tests/test_foo.py")
    assert is_ignored_path("src/__generated__/schema.ts")
    assert is_ignored_path("dist/bundle.js")
    assert is_ignored_path("node_modules/lib/index.js")


def test_real_source_not_ignored() -> None:
    assert not is_ignored_path("app/services/user.py")
    assert not is_ignored_path("src/components/Button.tsx")


def test_skip_dirs_superset_of_profiler_dirs() -> None:
    for d in {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}:
        assert d in SKIP_DIRS
