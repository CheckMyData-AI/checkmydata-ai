"""Per-request usage sinks for LLM calls (R2 / C1).

A ``UsageSink`` is observed by every LLM call so that token counts can be
recorded uniformly across the codebase (chat route, MCP tools, planner,
validator, repair) without each caller wiring its own DB write.

Three concrete sinks ship here:

* :class:`NullUsageSink` — default; observes silently. Used when there is no
  user/project context (eval harness, ad-hoc scripts).
* :class:`AccumUsageSink` — pure in-process accumulator. Useful for tests and
  for back-compat with code that previously held its own running totals dict.
* :class:`DbUsageSink` — persists each call via
  :class:`~app.services.usage_service.UsageService` and re-checks the user's
  token budget after the write. The budget reason is sticky so the
  orchestrator can hard-stop at the next safe boundary (F-BILL-05). A failing
  DB write is logged at WARNING and swallowed — a transient telemetry error
  must never abort the agent run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.models.base import async_session_factory
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost for this call, or None when the model is not in the price table.

    Deliberately UNGUARDED. `observe` already wraps its whole body in a broad handler,
    and the router wraps the `observe` call in another — a third would be a suppression
    that suppresses nothing, and the silent-degradation ratchet is right to count it.
    """
    from app.services.cost_estimation_service import estimate_cost

    return estimate_cost(model, prompt_tokens, completion_tokens)


@runtime_checkable
class UsageSink(Protocol):
    """Protocol observed by :class:`app.llm.router.LLMRouter` after each call."""

    async def observe(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str,
        model: str,
    ) -> None: ...

    def budget_exceeded(self) -> str | None:
        """Return a sticky reason once the user's budget is breached, else ``None``."""
        ...


@dataclass
class NullUsageSink:
    """No-op sink. Default when no user/project context is available."""

    async def observe(self, **_: Any) -> None:  # noqa: D401 — protocol shape
        return None

    def budget_exceeded(self) -> str | None:
        return None


@dataclass
class AccumUsageSink:
    """In-process accumulator. ``total_tokens`` falls back to prompt+completion when 0."""

    totals: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )

    async def observe(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str,
        model: str,
    ) -> None:
        self.totals["prompt_tokens"] += prompt_tokens
        self.totals["completion_tokens"] += completion_tokens
        self.totals["total_tokens"] += total_tokens or (prompt_tokens + completion_tokens)

    def budget_exceeded(self) -> str | None:
        return None


class DbUsageSink:
    """Persists usage per call via :class:`UsageService`, and optionally re-checks the
    user's budget. The reason is sticky so the orchestrator can hard-stop at
    the next safe boundary (F-BILL-05).

    **`gate` separates two jobs that are not the same.** Counting a call and refusing the
    next one belong together for a chat request — the person is waiting, and the next call
    is theirs to authorise. For background indexing they do not: `generate_docs` makes
    roughly 758 LLM calls per rebuild, and halting a rebuild because an account is over its
    monthly allowance is a worse product than one whose usage figure is short.

    Under per-account OpenRouter keys the money is right either way: OpenRouter counts and
    the key's own ceiling stops the spend. What a non-gating sink protects is the display,
    which was understating what customers spent because those routers recorded nothing.

    A flag rather than a second class, because two objects doing this recording would
    drift and the recording is the half that must not.
    """

    def __init__(
        self,
        *,
        user_id: str,
        project_id: str,
        session_id: str | None = None,
        message_id: str | None = None,
        accum: AccumUsageSink | None = None,
        gate: bool = True,
    ) -> None:
        self._user_id = user_id
        self._project_id = project_id
        self._session_id = session_id
        self._message_id = message_id
        self._accum = accum
        self._gate = gate
        self._budget_reason: str | None = None

    async def observe(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str,
        model: str,
    ) -> None:
        try:
            async with async_session_factory() as session:
                svc = UsageService()
                await svc.record_usage(
                    session,
                    user_id=self._user_id,
                    project_id=self._project_id,
                    session_id=self._session_id,
                    message_id=self._message_id,
                    provider=provider,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    # Was None, so `estimated_cost_usd` was null on every one of the
                    # 6 479 rows and `/api/usage` could report tokens but never money.
                    # The estimator already existed and was only wired into the four
                    # `chat.py` call sites, which cover the request but not the
                    # per-LLM-call sink that fires far more often.
                    estimated_cost_usd=_estimate_cost(model, prompt_tokens, completion_tokens),
                )
                if self._gate:
                    # Skipped entirely, not merely ignored: this runs once per LLM call and
                    # `check_token_budget` sums a month of `token_usage` each time.
                    reason = await svc.check_token_budget(session, self._user_id)
                    if reason:
                        self._budget_reason = reason
        except Exception:
            # Telemetry failures must never abort the agent run.
            logger.warning(
                "DbUsageSink.observe failed for user=%s project=%s provider=%s model=%s",
                self._user_id[:8] if self._user_id else "?",
                self._project_id[:8] if self._project_id else "?",
                provider,
                model,
                exc_info=True,
            )

        if self._accum is not None:
            try:
                await self._accum.observe(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    provider=provider,
                    model=model,
                )
            except Exception:
                logger.warning("DbUsageSink accum.observe failed", exc_info=True)

    def budget_exceeded(self) -> str | None:
        return self._budget_reason


__all__ = [
    "AccumUsageSink",
    "DbUsageSink",
    "NullUsageSink",
    "UsageSink",
]
