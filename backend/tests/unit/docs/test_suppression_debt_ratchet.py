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
    # 618 → 621 on 2026-08-31. Three, all on the Stripe seam, and all three swallow a
    # failure whose propagation would cost more than the thing it was reporting:
    #
    #   `BillingService.reconcile`   — per subscription. One row Stripe cannot answer for
    #                                  must not end the sweep over the others; the whole
    #                                  point of reconciliation is the rows nobody noticed.
    #   `_reconcile_billing`         — the maintenance loop runs six jobs. A billing sweep
    #                                  that can abort it takes learning decay, insight
    #                                  expiry and the analytics prune with it.
    #   `_register_entitlements`     — a cloud image that cannot load its billing layer
    #                                  degrades to permissive rather than to broken. The
    #                                  alternative is an outage caused by the component
    #                                  whose job is collecting money for uptime.
    #
    # Each logs at WARNING or ERROR with the id it was working on, and none returns a
    # value that reads as success — the shape this ratchet exists to catch.
    # 614 → 618 on 2026-08-31. Four, all in the recovery path, and each one swallows a
    # failure whose propagation would destroy the thing it was reporting on:
    #
    #   `StaleRunReaper._run_meta`         — an unreadable `meta_json` must not stop the
    #                                        reap; the replacement run just loses its
    #                                        inherited `force_full`.
    #   `StaleRunReaper._requeue_attempts` — an uncountable attempt history returns THE
    #                                        BOUND, not zero, so a failure to count
    #                                        cannot uncap the retry.
    #   `StaleRunReaper._requeue`          — per run. The reap IS the recovery; a failed
    #                                        re-enqueue must not leave `running` rows
    #                                        unreaped and the UI spinning.
    #   `run_repo_index_task`              — the `IndexingRun` row is bookkeeping and the
    #                                        index is the work. Falling back to a bare
    #                                        workflow is exactly the previous behaviour,
    #                                        which indexed correctly.
    #
    # Every one logs at WARNING with the project id. None returns a value that reads as
    # success: the shape this ratchet exists to catch is the `except: pass` that makes a
    # broken thing look finished.
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
    # 2026-08-28: `except Exception` raised by one for `PgVectorStore.close()`, which
    # swallows a pool-close failure — the store is being torn down, and raising there
    # would mask whatever was actually being shut down.
    #
    # The `noqa` count went 128 -> 129: `app/models/__init__.py` gained a `DocEmbedding` re-export
    # carrying the same unused-import suppression the other forty-two imports in that
    # file already carry. Convention, not debt.
    #
    # A SECOND one was added and then deleted — a suppression on an inner function's
    # untyped argument, where annotating it cost one word. That is the answer this
    # ratchet exists to provoke, and it is why the raise here is one rather than two.
    # 621 → 623 on 2026-08-31, both on the credit path, and both swallow a failure that
    # would cost more than the thing it reports:
    #
    #   `_credit_top_up`  — the charge has ALREADY succeeded. Raising makes Stripe retry
    #                       a payment that cannot be un-taken, so the honest outcome is
    #                       an ERROR line carrying the amount and session id for a human
    #                       to finish: "PAID BUT NOT CREDITED".
    #   `_renew_credit`   — a failed ceiling update must not fail the webhook. Stripe
    #                       would retry, the idempotency claim would refuse it, and the
    #                       renewal would be lost rather than merely late; the
    #                       reconciliation sweep is what catches it.
    #
    # 623 -> 625 on 2026-09-01, both the same shape in the two indexing pipelines: the
    # step that binds a per-run metering sink cannot resolve the project's owner. The
    # question a raise has to answer is "what is the alternative", and here it is
    # "refuse to index" -- trading a working rebuild for a correct usage number, when
    # the money is already bounded by the account's own OpenRouter ceiling. So both log
    # WARNING with the project id and continue unmetered, which understates one
    # customer's spend on one run and is visible in the log rather than silent.
    #
    # 625 -> 624 on 2026-09-01, with no handler removed: the counter stopped counting
    # comment lines, and one of the 625 was prose describing a handler rather than a
    # handler.
    "except Exception": 624,
    # 53 -> 55 on 2026-09-01, and this rise is the counter getting MORE accurate rather
    # than debt growing. The old regex required `except …:` and `pass` on consecutive
    # lines, so a comment between them hid the handler entirely. Two were hiding:
    #
    #   `vector_store.py:43`      — a probe for the embedder's max-token attribute;
    #                               "attribute absent or any other error — skip silently".
    #   `db_index_service.py:128` — artifact cleanup inside `delete_all`, silenced so
    #                               cleanup cannot break that method's public contract.
    #
    # Both predate this change and both are defensible; they are recorded here rather
    # than fixed, because a counter fix is not a licence to edit unrelated handlers.
    "except ...: pass": 55,
    "# type: ignore": 49,
    # 129 → 130 on 2026-08-31. One, in `BillingService.reconcile`: BLE001 on a per-row
    # handler, because a subscription Stripe cannot answer for must not end the sweep
    # over the rest — reconciliation exists precisely for the rows nobody noticed.
    #
    # It was three. Two came from `global _provider` in the entitlement registry and
    # this ratchet is why they are gone: asked whether they were worth recording, the
    # answer was to hold the provider in a one-slot dict and need no suppression at all.
    "# noqa": 130,
}

PATTERNS: dict[str, re.Pattern[str]] = {
    "except Exception": re.compile(r"except\s+Exception\b"),
    # A handler whose entire body is `pass` — the shape that discards an error with no
    # trace at all. Multi-line bodies that merely log are a different, milder thing.
    "except ...: pass": re.compile(r"except[^\n]*:\s*\n\s*pass\b"),
    "# type: ignore": re.compile(r"#\s*type:\s*ignore"),
    "# noqa": re.compile(r"#\s*noqa"),
}


#: Directives that only take effect TRAILING a line of code. `# type: ignore` on its own
#: line suppresses nothing in mypy, and a lone `# noqa` suppresses nothing in ruff — both
#: must sit on the line that errors. So a full-line comment naming one is prose.
_TRAILING_DIRECTIVES = frozenset({"# type: ignore", "# noqa"})


def _strip_comment_lines(text: str) -> str:
    """Blank out whole-line comments, keeping the line structure.

    Blanked rather than deleted so the multi-line `except ...: pass` pattern still sees the
    same shape: a comment between `except` and `pass` does not stop the body being `pass`.
    """
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


def _count() -> dict[str, int]:
    """Count SUPPRESSIONS, not mentions of them.

    This ratchet counted its own explanations four times in one session — twice on
    `except Exception`, twice on `# type: ignore`, including a comment that said "getattr
    rather than `# type: ignore`" while adding no suppression at all (mypy: 0 errors). Each
    time the response was to reword the prose, which teaches an author to hide the word
    rather than to weigh the suppression. A check that punishes explaining yourself is
    worse than no check, so the rule is now structural: prose cannot suppress anything.
    """
    totals = dict.fromkeys(PATTERNS, 0)
    for path in APP.rglob("*.py"):
        raw = path.read_text(encoding="utf-8")
        text = _strip_comment_lines(raw)
        for name, pattern in PATTERNS.items():
            if name in _TRAILING_DIRECTIVES:
                # One per line at most: a line has one effective suppression.
                for line in text.splitlines():
                    m = pattern.search(line)
                    if m and line[: m.start()].strip():
                        totals[name] += 1
            else:
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
    assert PATTERNS["# noqa"].findall("import x  # noqa" + ": F401")


class TestTheCounterCountsSuppressionsNotMentions:
    """The guard for the guard.

    This ratchet counted its own explanations four times in one session. Each time the
    response was to reword the comment, which is the wrong lesson: it teaches an author to
    avoid naming a suppression rather than to weigh whether to add one.
    """

    def test_a_comment_naming_a_directive_is_not_counted(self, tmp_path) -> None:
        """The exact comment that tripped it: prose saying a suppression was AVOIDED."""
        import re

        line = "            # getattr rather than `# type: ignore`: the async stub types this"
        pattern = re.compile(r"#\s*type:\s*ignore")
        stripped = _strip_comment_lines(line)
        assert pattern.search(line), "the raw line does contain the marker"
        assert not pattern.search(stripped), "a whole-line comment must not count"

    def test_a_real_trailing_suppression_is_counted(self) -> None:
        """The control. Without it, a counter that counts nothing passes every ceiling."""
        import re

        line = "    x = frobnicate(y)  # type: ignore[arg-type]"
        pattern = re.compile(r"#\s*type:\s*ignore")
        stripped = _strip_comment_lines(line)
        m = pattern.search(stripped)
        assert m and stripped[: m.start()].strip(), "a trailing suppression must count"

    def test_a_lone_directive_line_is_not_counted(self) -> None:
        """`# type: ignore` on its own line suppresses nothing in mypy, and a lone
        `# noqa` suppresses nothing in ruff. Both must trail the erroring line."""
        import re

        pattern = re.compile(r"#\s*noqa")
        stripped = _strip_comment_lines("    # noqa")
        assert not pattern.search(stripped)

    def test_prose_naming_a_handler_is_not_counted(self) -> None:
        import re

        pattern = re.compile(r"except\s+Exception\b")
        stripped = _strip_comment_lines("    # wrapped in except Exception so a probe cannot")
        assert not pattern.search(stripped)

    def test_a_handler_with_a_comment_before_pass_still_counts(self) -> None:
        """The false NEGATIVE this fix removed. Two real handlers were invisible because a
        comment sat between `except` and `pass`."""
        import re

        pattern = re.compile(r"except[^\n]*:\s*\n\s*pass\b")
        src = "    try:\n        f()\n    except Exception:\n        # why\n        pass\n"
        assert not pattern.search(src), "the raw form is what the old counter missed"
        assert pattern.search(_strip_comment_lines(src)), "blanking must reveal it"
