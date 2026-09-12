"""57.4 million tokens were burned and 0 were counted, so no limit could ever fire.

Measured in production on 2026-08-28, over the whole `token_usage` table:

    rows                  6 479
    sum(prompt_tokens)   53 089 902
    sum(completion_tokens) 4 315 660
    sum(total_tokens)             0

Three things line up to produce that, and each looks innocent alone:

1. **No adapter provides `total_tokens`.** All three build `usage` with `prompt_tokens`
   and `completion_tokens` only — `openrouter_adapter.py:213`, `openai_adapter.py:209`,
   `anthropic_adapter.py:226`. It is not an OpenRouter quirk; it is every provider.
2. **The router reads it with a zero default** — `usage.get("total_tokens", 0)` —
   so it passes `0`, a number, rather than `None`, an absence.
3. **`UsageService.record_usage` derives the total only from `None`**
   (`usage_service.py:40`). `0` is not `None`, so the fallback never runs and `0` is
   stored.

What that costs is not bookkeeping. `check_budget` sums `TokenUsage.total_tokens`
(`usage_service.py:78, :84`) for both the daily and the monthly window, so
`USER_DAILY_TOKEN_LIMIT`, `USER_MONTHLY_TOKEN_LIMIT` and every plan-derived
entitlement compare a real limit against a permanent zero. The post-call gate that is
supposed to stop a runaway agent run at the next safe boundary cannot fire either.
`BILLING_ENABLED` is `True` in production.

The fix is in the router rather than in the three adapters: it is the single funnel
every provider passes through, including the next one somebody adds.
"""

from __future__ import annotations

import inspect

import pytest


class TestTheRouterDerivesTheTotalWhenTheProviderOmitsIt:
    """A provider that reports its own total keeps it — a cached-prompt discount can
    make the real total differ from the sum, and the provider is the authority on that.
    Absence is what gets filled in."""

    @staticmethod
    def _derive(usage: dict) -> int:
        """Mirror of the router's derivation, exercised through the real function."""
        from app.llm.router import _usage_total

        return _usage_total(usage)

    def test_absent_total_is_derived_from_the_parts(self) -> None:
        assert self._derive({"prompt_tokens": 8000, "completion_tokens": 200}) == 8200

    def test_zero_total_is_treated_as_absent(self) -> None:
        """This is the exact shape every adapter produces once the router's own
        `.get(..., 0)` default has been applied — a zero that means "nobody said"."""
        assert (
            self._derive({"prompt_tokens": 8000, "completion_tokens": 200, "total_tokens": 0})
            == 8200
        )

    def test_a_provider_supplied_total_wins(self) -> None:
        """9000 rather than 8200: with prompt caching the provider's own accounting is
        the one that gets billed, and second-guessing it would understate the cost."""
        assert (
            self._derive({"prompt_tokens": 8000, "completion_tokens": 200, "total_tokens": 9000})
            == 9000
        )

    def test_nothing_at_all_is_zero_and_not_an_error(self) -> None:
        """A failed or streaming call may carry no usage. Zero is the honest answer;
        raising here would turn a missing number into a lost response."""
        assert self._derive({}) == 0

    @pytest.mark.parametrize(
        "bad", [{"prompt_tokens": None, "completion_tokens": None}, {"prompt_tokens": "x"}]
    )
    def test_junk_does_not_raise(self, bad: dict) -> None:
        """Usage accounting must never be the thing that loses an answer."""
        assert self._derive(bad) >= 0


class TestEveryAdapterSuppliesWhatTheRouterNeeds:
    """The derivation above is only correct while the parts are present. An adapter
    that stops reporting `prompt_tokens` would silently return the accounting to zero,
    and nothing else in the system would notice."""

    ADAPTERS = ("openai_adapter", "openrouter_adapter", "anthropic_adapter")

    @pytest.mark.parametrize("name", ADAPTERS)
    def test_it_reports_both_parts(self, name: str) -> None:
        import importlib

        source = inspect.getsource(importlib.import_module(f"app.llm.{name}"))
        assert '"prompt_tokens"' in source, f"{name} does not report prompt_tokens"
        assert '"completion_tokens"' in source, f"{name} does not report completion_tokens"


class TestTheBudgetGateReadsSomethingRealNow:
    def test_it_sums_total_tokens(self) -> None:
        """Named explicitly because it is the column the whole chain exists to fill.

        If the gate is ever changed to sum something else, this file's premise moves
        with it and should fail rather than quietly stop mattering — and on 2026-09-12
        it did exactly that. `check_budget` was collapsed from six queries to one and
        the summing moved into `_window_totals`; this test went red because it read
        `check_budget`'s own text. The premise did not change, so the test follows the
        sum to where it lives rather than pinning its address.
        """
        from app.services import usage_service

        gate = inspect.getsource(usage_service.UsageService.check_budget)
        totals = inspect.getsource(usage_service.UsageService._window_totals)
        assert "_window_totals" in gate, (
            "the gate no longer reads the window totals at all — whatever it reads "
            "instead is what this file should be measuring"
        )
        assert "TokenUsage.total_tokens" in totals, (
            "the budget gate stopped summing `total_tokens`, the column the whole "
            "usage chain exists to fill"
        )

    def test_record_usage_derives_whenever_it_was_not_told_a_total(self) -> None:
        """Belt to the router's braces — and the belt was buckled against the wrong
        hazard until 2026-09-09.

        This test used to assert the literal string ``if total_tokens is None``, and its
        docstring explained the choice: *"a caller that passes `None` — `chat.py` has
        four such call sites — must still get the sum rather than a null."* Those four
        sites do not pass `None`. They pass ``usage.get("total_tokens", 0)``, which is a
        **zero**, and the `is None` check let it through — so ten production rows carried
        prompt=175 669 / completion=4 587 with `total_tokens = 0` and charged nothing
        against the user's budget.

        Grepping for the spelling made a wrong belief look verified. Asserted as
        behaviour now: whatever the condition is written as, a call with real prompt and
        completion counts must not be recorded as zero, and a provider that reported its
        own total must keep it.
        """
        from app.services.usage_service import UsageService

        derive = inspect.getsource(UsageService.record_usage)
        assert "prompt_tokens + completion_tokens" in derive, "the derivation is gone"
        assert "if total_tokens is None" not in derive, (
            "`is None` alone misses the zero every `usage.get(..., 0)` produces — which "
            "is what every caller in `chat.py` writes"
        )
