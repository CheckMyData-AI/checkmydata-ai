"""Suppression debt is counted, not remembered.

The board carries two rows — `CB-M5` (silent error swallowing) and `CB-L1` (type and
lint suppressions) — and each quotes a figure. Recounted on 2026-08-25, all four had
moved, and the largest by 18%:

| Metric | On the board | Recounted |
|---|---|---|
| `except Exception` | 516 | 611 |
| `except …: pass` | 51 | 53 |
| `# type: ignore` | 47 | 49 |
| `# noqa` | 104 | 128 |

The board is not careless — nothing recomputes those numbers, so they were true once and
have been read as current ever since. Even the audit that raised this drifted: it
reported 54 `except …: pass` on 2026-08-23 and there are 53 today. A number written by
hand starts ageing the moment it is written.

**A ratchet, not a target.** These ceilings are today's counts. Going down is free.
Going up fails, and the fix is not to raise the number quietly — it is to decide, in the
same commit, that this particular suppression is worth it and say so by raising the
ceiling deliberately. That turns "the debt grew 18% and nobody noticed" into a line in a
diff somebody reviewed.

`except Exception` is deliberately included even though most uses here are legitimate —
metrics, best-effort cleanup, diagnostics that must never break a request. The point is
not that 611 is wrong; it is that the 612th should be a decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[4] / "backend" / "app"

#: Counts measured 2026-08-25 over `backend/app/`. Lower them as suppressions go; raise
#: one only in the same commit as the suppression it admits, so the increase is reviewed.
CEILINGS: dict[str, int] = {
    # 611 → 613 on 2026-08-25, in two steps, and both raises are the mechanism working
    # rather than exceptions to it. `StaleRunReaper._catalog` (N3) swallows a failure to
    # write the error catalog, because a diagnostic that can abort the recovery it is
    # describing would leave `running` rows unreaped. `report_capabilities` (N4/N8)
    # swallows a claim it cannot evaluate, because a boot check that stops a boot is a
    # worse bug than the one it reports.
    #
    # Both arrived from *other* branches while this one was open, and CI caught each on
    # the way in. Worth naming, because it is the cost of the design: the counter is
    # shared, so concurrent branches each adding a justified suppression will each turn
    # this red. That friction is the point — every one of those raises is a sentence
    # somebody had to write — but a burst of five parallel PRs makes it feel like noise
    # rather than a decision, and it should be read as the latter.
    # 2026-08-28, both raised by one: `PgVectorStore.close()` swallows a pool-close
    # failure (the store is being torn down; raising there would mask whatever was
    # actually being shut down), and `app/models/__init__.py` gained
    # a `DocEmbedding` re-export carrying the same unused-import suppression every one
    # of the other forty imports in that file already carries — convention, not debt.
    "except Exception": 614,
    "except ...: pass": 53,
    "# type: ignore": 49,
    "# noqa": 129,
}

PATTERNS: dict[str, re.Pattern[str]] = {
    "except Exception": re.compile(r"except\s+Exception\b"),
    # A handler whose entire body is `pass` — the shape that discards an error with no
    # trace at all. Multi-line bodies that merely log are a different, milder thing.
    "except ...: pass": re.compile(r"except[^\n]*:\s*\n\s*pass\b"),
    "# type: ignore": re.compile(r"#\s*type:\s*ignore"),
    "# noqa": re.compile(r"#\s*noqa"),
}


def _count() -> dict[str, int]:
    totals = dict.fromkeys(PATTERNS, 0)
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name, pattern in PATTERNS.items():
            totals[name] += len(pattern.findall(text))
    return totals


@pytest.fixture(scope="module")
def counts() -> dict[str, int]:
    return _count()


def test_there_is_source_to_count(counts: dict[str, int]) -> None:
    """Zero everywhere means the walk found nothing, which passes every ceiling."""
    assert sum(counts.values()) > 100, f"counted almost nothing: {counts}"
    assert len(list(APP.rglob("*.py"))) > 100


@pytest.mark.parametrize("metric", sorted(CEILINGS))
def test_suppression_debt_has_not_grown(metric: str, counts: dict[str, int]) -> None:
    actual, ceiling = counts[metric], CEILINGS[metric]
    assert actual <= ceiling, (
        f"`{metric}` is at {actual}, above the recorded ceiling of {ceiling}. Either "
        "remove the new suppression, or raise the ceiling in this same commit so the "
        "decision is reviewed rather than discovered by the next audit."
    )


def test_a_ceiling_far_above_reality_is_reported(counts: dict[str, int]) -> None:
    """A ratchet that never tightens stops being one.

    When suppressions are removed the ceiling should follow them down, or it drifts back
    into being a number nobody maintains — the exact failure this file exists to end.
    """
    slack = {m: (CEILINGS[m], counts[m]) for m in CEILINGS if counts[m] < CEILINGS[m] - 15}
    assert not slack, (
        "these ceilings are more than 15 above the real count — lower them to today's "
        f"numbers so the ratchet keeps biting: {slack}"
    )


def test_the_patterns_match_what_they_claim() -> None:
    """Each pattern pinned against the shape it is meant to catch and one it is not."""
    assert PATTERNS["except Exception"].findall("except Exception:") == ["except Exception"]
    assert PATTERNS["except Exception"].findall("except ExceptionGroup:") == []

    body_is_pass = "try:\n    x()\nexcept ValueError:\n    pass\n"
    assert PATTERNS["except ...: pass"].findall(body_is_pass)
    body_logs = "try:\n    x()\nexcept ValueError:\n    logger.debug('x')\n"
    assert PATTERNS["except ...: pass"].findall(body_logs) == []

    assert PATTERNS["# type: ignore"].findall("x = y  # type: ignore[arg-type]")
    assert PATTERNS["# noqa"].findall("import x  # noqa: F401")
