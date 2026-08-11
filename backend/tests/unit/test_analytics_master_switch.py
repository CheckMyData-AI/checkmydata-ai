"""C14 — why the analytics master switch is NOT re-checked in the worker.

The obvious reading of carry-over C14 is "the executor never checks
`ANALYTICS_COLLECT_ENABLED`, so add the check". That was implemented, and a test that
had been **silently skipping for months** — `test_analytics_cron.py::TestWorkerJob` —
ran for the first time and rejected it. The test was right.

The ARQ job is only ever enqueued by `_dispatch_analytics_collect_wave`, which already
gates on the flag. Re-checking inside the worker reads the same setting **a second
time, in a different process**, whose configuration was loaded at *its* start-up. The
window that closes is seconds — a job queued just before the operator flips the switch.
The window that opens is the entire lifetime of two processes holding different values,
during which the worker silently refuses work it was correctly given. That is a worse
failure than the one being fixed, and a silent one.

**What C14 actually complained about** is different, and still open: the flag is read
once at start-up, so a config change without a restart leaves collection dormant while
the status reads `never_collected` — which looks like "nothing configured" rather than
"switched off". That is a legibility defect, not a gating one, and the fix belongs in
whatever renders that status, not in the worker.
"""

from __future__ import annotations

import ast
from pathlib import Path

WORKER = Path(__file__).resolve().parents[2] / "app" / "worker.py"


def test_the_worker_does_not_second_guess_the_dispatcher():
    """Pins the rejection so the obvious fix is not re-attempted as an oversight."""
    tree = ast.parse(WORKER.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_analytics_collect"
    )
    names = {node.attr for node in ast.walk(fn) if isinstance(node, ast.Attribute)} | {
        node.id for node in ast.walk(fn) if isinstance(node, ast.Name)
    }

    assert "analytics_collect_enabled" not in names, (
        "the executor must not re-read the master switch: its process may hold a stale "
        "value and silently refuse work the dispatcher correctly queued"
    )
