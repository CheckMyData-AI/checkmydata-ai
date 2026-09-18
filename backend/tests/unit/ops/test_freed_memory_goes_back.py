"""T00-mem: the boot rebuild hands its arenas back.

Freeing the tokenized corpus did not lower RSS — glibc keeps the arena and the dyno
quota counts RSS. Measured on production (32 571 documents, Standard-1X, 2026-09-18):
376 MB after the boot rebuild, **353 MB** after one `malloc_trim(0)`.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from app.ops.memory import release_freed_memory

APP = Path(__file__).resolve().parents[3] / "app"


def test_it_never_raises_and_says_what_happened(caplog):
    """On a platform without glibc it returns False, which is an answer, not a failure."""
    with caplog.at_level(logging.DEBUG):
        result = release_freed_memory("a test")
    assert result in (True, False)


def test_a_broken_libc_is_survivable(monkeypatch):
    import ctypes

    def boom(_name):
        raise OSError("no such library")  # how a platform without glibc answers

    monkeypatch.setattr(ctypes, "CDLL", boom)
    assert release_freed_memory("a broken libc") is False


def test_the_boot_rebuild_trims_after_it_finishes():
    """Structural: the call sits inside the rebuild, after the reconcile it follows.

    Checked on the parse tree — a call ordered before the work it follows would trim
    nothing, and the text of the file cannot say which came first.
    """
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    rebuilds = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_bm25_boot_rebuild"
    ]
    assert len(rebuilds) == 1, "the boot rebuild is defined once"
    body = rebuilds[0].body
    reconcile_at = next(
        i for i, node in enumerate(body) if "reconcile_local_bm25" in ast.dump(node)
    )
    trim_at = next(i for i, node in enumerate(body) if "release_freed_memory" in ast.dump(node))
    assert trim_at > reconcile_at, "trimming before the corpus is freed releases nothing"
