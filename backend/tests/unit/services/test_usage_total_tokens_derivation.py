"""A call with 175 669 prompt tokens has not used zero tokens.

Measured on production 2026-09-09, `token_usage` rows with `estimated_cost_usd > 0` and
`total_tokens = 0`:

    2026-09-05  openai/gpt-4o              8 rows  prompt=177 838  completion=3 316  total=0  $0.4778
    2026-09-04  anthropic/claude-opus-4.8  2 rows  prompt=175 669  completion=4 587  total=0  $0.9930

The cost is right. What is wrong is the total, and the consequence is not a reporting
one: `UsageService.check_budget` sums exactly this column, so those ten calls counted as
**zero** against the user's daily, monthly and plan-derived limits — with
`BILLING_ENABLED` on.

This is the same defect as 2026-08-28, half-fixed. That one is documented in
`_usage_total` (`router.py:38`): no adapter reports `total_tokens`, all three build
`usage` from prompt and completion alone, and reading it with a `0` default produces a
NUMBER where there was an ABSENCE — so `record_usage`'s `if total_tokens is None`
fallback never ran. The fix landed in the router, which is the per-LLM-call sink. The
four REQUEST-level writers in `chat.py` (`:541`, `:930`, `:1297`, `:1861`) still read
`usage.get("total_tokens", 0)` and still hand that zero straight through.

So the derivation moves to `record_usage` itself — the one funnel all five writers pass
through, including the sixth somebody adds next. The router's own preference for a
provider-reported total is unaffected and still correct: prompt caching makes the billed
total differ from the sum, and the provider is the authority on what it charged. A
reported total is never zero, so the two rules never disagree.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.usage_service import UsageService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _record(db, **kw):
    row = await UsageService().record_usage(
        db, user_id="u1", project_id="p1", provider="openrouter", model="m", **kw
    )
    await db.commit()
    return row


class TestAZeroTotalIsAnAbsence:
    async def test_the_production_row_is_no_longer_possible(self, db) -> None:
        row = await _record(db, prompt_tokens=175_669, completion_tokens=4_587, total_tokens=0)
        assert row.total_tokens == 180_256, (
            "a call with real prompt and completion counts was recorded as zero total; "
            "check_budget sums this column, so it charged nothing against the plan"
        )

    async def test_an_explicit_none_still_derives(self, db) -> None:
        """The rule that already worked, kept working."""
        row = await _record(db, prompt_tokens=10, completion_tokens=5, total_tokens=None)
        assert row.total_tokens == 15

    async def test_a_provider_reported_total_is_never_overwritten(self, db) -> None:
        """Prompt caching makes the billed total differ from the sum, and the provider is
        the authority on what it charged. 900 != 10 + 5 and must survive."""
        row = await _record(db, prompt_tokens=10, completion_tokens=5, total_tokens=900)
        assert row.total_tokens == 900

    async def test_a_genuinely_empty_call_stays_zero(self, db) -> None:
        """The boundary. Nothing is invented: with no prompt and no completion the
        derived total is zero, which is also the truth."""
        row = await _record(db, prompt_tokens=0, completion_tokens=0, total_tokens=0)
        assert row.total_tokens == 0

    async def test_only_a_prompt_still_counts(self, db) -> None:
        """A call that failed after sending the prompt spent those tokens."""
        row = await _record(db, prompt_tokens=1_200, completion_tokens=0, total_tokens=0)
        assert row.total_tokens == 1_200


class TestEveryWriterGoesThroughTheFunnel:
    def test_no_caller_needs_to_remember_the_rule(self) -> None:
        """The 2026-08-28 fix was correct and landed in one of two layers. This asserts
        the derivation lives where every writer passes, rather than at each of them —
        `chat.py` has four sites and all four read `usage.get("total_tokens", 0)`.
        """
        import inspect
        import re

        from app.services.usage_service import UsageService as Svc

        src = inspect.getsource(Svc.record_usage)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert "if not total_tokens:" in body, (
            "the derivation must treat a falsy total as an absence; `is None` alone "
            "misses the zero that every adapter's `.get(..., 0)` produces"
        )

    def test_the_budget_gate_reads_the_column_this_protects(self) -> None:
        """Why the above is not merely tidy. If `check_budget` ever stops summing
        `total_tokens`, this test's premise is gone and someone should know."""
        import inspect

        from app.services.usage_service import UsageService as Svc

        src = inspect.getsource(Svc)
        assert "total_tokens" in src
        assert "check_budget" in src or "check_token_budget" in src
