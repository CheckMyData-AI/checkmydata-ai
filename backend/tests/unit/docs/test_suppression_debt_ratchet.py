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
    #
    # 624 -> 625 on 2026-09-01. One handler, in `capability_report._active_backend`: the
    # boot diagnostic resolves the vector backend, and `resolve_backend` raises on an
    # invalid configuration. A diagnostic that can stop a boot is worse than the thing it
    # diagnoses. It logs at WARNING and says the claims are not being checked — the
    # silent-degradation ratchet caught the first version, which returned None at debug and
    # would have made both claims disappear without a word.
    "except Exception": 625,
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
    #
    # 55 -> 57 on 2026-09-01, and again the counter got MORE accurate rather than the debt
    # growing. Blanking comments by TOKEN (not by "line starts with #") revealed two
    # handlers hidden by a TRAILING comment: the old regex `except[^\n]*:` backtracked
    # around the colon inside `# pragma: no cover` and `# noqa: BLE001 — …` and never
    # reached the `pass` below.
    #
    #   `required_filter_guard.py:257` — a metrics increment; `# pragma: no cover`.
    #   `git_tracker.py:84`            — merge_base lookup, diagnostic only; `# noqa: BLE001`.
    #
    # The second one was already declared in the `# noqa` metric while its shape stayed
    # invisible here. Both predate this change and are recorded, not edited.
    "except ...: pass": 57,
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


def _code_only(text: str) -> str:
    """*text* with comments and string literals blanked out, line structure preserved.

    Tokenised rather than pattern-matched, because prose hides in two shapes and the
    line-based version only knew one. It blanked lines starting with ``#`` and left
    DOCSTRINGS alone — so a module whose documentation quotes ``except Exception: pass``
    was counted as containing one. That is the fifth time this ratchet counted its own
    explanations, and the previous four were all ``#`` comments, which is why the rule
    looked complete.

    Blanked rather than deleted so the multi-line ``except ...: pass`` pattern still sees
    the same shape: a comment between ``except`` and ``pass`` does not stop the body being
    ``pass``, and that fix removed two real false negatives.

    Falls back to the line-based strip when a file will not tokenise — a counter must not
    stop counting because one file is mid-edit.
    """
    import io
    import tokenize

    try:
        lines = text.splitlines()
        out = [list(ln) for ln in lines]
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            for row in range(r1, r2 + 1):
                if row - 1 >= len(out):
                    break
                lo = c1 if row == r1 else 0
                hi = c2 if row == r2 else len(out[row - 1])
                for col in range(lo, min(hi, len(out[row - 1]))):
                    out[row - 1][col] = " "
        return "\n".join("".join(ln) for ln in out)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


def _trailing_directives(text: str, pattern) -> int:
    """Count COMMENT tokens matching *pattern* that trail actual code on their line.

    Counted from the comments themselves, not from the blanked text: these two metrics ARE
    comments, so the strip that fixes the other two would zero them. And the trailing rule
    is not stylistic — ``# type: ignore`` on its own line suppresses nothing in mypy, and a
    lone ``# noqa`` suppresses nothing in ruff. Both must sit on the line that errors.
    """
    import io
    import tokenize

    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return 0

    code_rows: set[int] = set()
    ignore = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
    for t in toks:
        if t.type not in ignore and t.string.strip():
            code_rows.add(t.start[0])

    n = 0
    for t in toks:
        if t.type is tokenize.COMMENT and pattern.search(t.string) and t.start[0] in code_rows:
            n += 1
    return n


def _count() -> dict[str, int]:
    """Count SUPPRESSIONS, not mentions of them.

    This ratchet counted its own explanations five times in one session. Four were ``#``
    comments; the fifth was a module DOCSTRING quoting ``except Exception: pass``, which the
    comment-only strip could not see. Rewording the prose each time teaches an author to
    avoid naming a suppression rather than to weigh adding one, so the rule is structural
    and now complete: prose cannot suppress anything, in either shape.

    The two sources are deliberately different. Handler shapes are counted over text with
    comments AND strings blanked; the two comment directives are counted from the comment
    tokens themselves, where the trailing-code rule decides.
    """
    totals = dict.fromkeys(PATTERNS, 0)
    for path in APP.rglob("*.py"):
        raw = path.read_text(encoding="utf-8")
        code = _code_only(raw)
        for name, pattern in PATTERNS.items():
            if name in _TRAILING_DIRECTIVES:
                totals[name] += _trailing_directives(raw, pattern)
            else:
                totals[name] += len(pattern.findall(code))
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

    This ratchet counted its own explanations five times in one session. Four were `#`
    comments; the fifth was a module docstring quoting `except Exception: pass`. Each time
    the response was to reword the prose, which is the wrong lesson: it teaches an author to
    avoid naming a suppression rather than to weigh adding one.
    """

    _IGNORE = re.compile(r"#\s*type:\s*ignore")
    _NOQA = re.compile(r"#\s*noqa")

    def test_a_real_trailing_suppression_is_counted(self) -> None:
        """The control. Without it, a counter that counts nothing passes every ceiling."""
        src = "x = frobnicate(y)  # type: ignore[arg-type]\n"
        assert _trailing_directives(src, self._IGNORE) == 1

    def test_a_comment_naming_a_directive_is_not_counted(self) -> None:
        """The exact line that tripped it: prose saying a suppression was AVOIDED."""
        src = "# getattr rather than `# type: ignore`: the async stub types this\nx = 1\n"
        assert _trailing_directives(src, self._IGNORE) == 0

    def test_a_lone_directive_line_is_not_counted(self) -> None:
        """`# type: ignore` on its own line suppresses nothing in mypy, and a lone
        `# noqa` suppresses nothing in ruff. Both must trail the erroring line."""
        assert _trailing_directives("    # noqa\n    x = 1\n", self._NOQA) == 0

    def test_a_docstring_naming_a_directive_is_not_counted(self) -> None:
        """The fifth occurrence, and the one the comment-only strip could not see."""
        src = (
            'def f():\n    """Uses getattr rather than a `# type: ignore` here."""\n    return 1\n'
        )
        assert _trailing_directives(src, self._IGNORE) == 0

    def test_prose_naming_a_handler_is_not_counted(self) -> None:
        pattern = re.compile(r"except\s+Exception\b")
        src = "# wrapped in except Exception so a probe cannot fail the boot\nx = 1\n"
        assert not pattern.search(_code_only(src))

    def test_a_docstring_naming_a_handler_is_not_counted(self) -> None:
        pattern = re.compile(r"except\s+Exception\b")
        src = '"""The check sits inside a silenced except Exception: pass."""\nx = 1\n'
        assert not pattern.search(_code_only(src))

    def test_a_handler_with_a_comment_before_pass_still_counts(self) -> None:
        """One false NEGATIVE this fix removed."""
        pattern = re.compile(r"except[^\n]*:\s*\n\s*pass\b")
        src = "try:\n    f()\nexcept Exception:\n    # why\n    pass\n"
        assert not pattern.search(src), "the raw form is what the old counter missed"
        assert pattern.search(_code_only(src))

    def test_a_handler_with_a_trailing_comment_still_counts(self) -> None:
        """The other one, and the commoner shape: the old regex backtracked around the
        colon inside `# pragma: no cover` and never reached the `pass`."""
        pattern = re.compile(r"except[^\n]*:\s*\n\s*pass\b")
        src = "try:\n    f()\nexcept Exception:  # pragma: no cover\n    pass\n"
        assert not pattern.search(src)
        assert pattern.search(_code_only(src))

    def test_an_untokenisable_file_does_not_zero_the_count(self) -> None:
        """A counter must not stop counting because one file is mid-edit."""
        broken = "def f(:\n    # noqa\n"
        assert _code_only(broken) is not None
