"""One shared ignore set for repo scanning (CODEIDX-C9).

Used by the project profiler, repo analyzer, and AST file collection so the
code graph, the profile, and the analyzer all agree on what to skip (tests,
generated output, vendored deps, build artefacts).
"""

from __future__ import annotations

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "vendor",
        "target",
        "coverage",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "__generated__",
        "generated",
        ".turbo",
        "out",
    }
)

# Directory names that are test roots (excluded from the code graph).
_TEST_DIRS: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec", "e2e"})


def is_ignored_path(rel_path: str) -> bool:
    """Return True if any path segment is a skipped / test / generated directory."""
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts[:-1]:  # directory segments only
        if p in SKIP_DIRS or p in _TEST_DIRS:
            return True
    return False
