"""P0-1c: the per-account OpenRouter key is minted, metered, renewed — and never used.

`provision()` creates a real key against OpenRouter, encrypts it into
`llm_credits.key_encrypted`, and is the only thing that ever decrypts it — inside the
same function, whose one caller discards the return value. `OpenRouterAdapter` binds
`settings.openrouter_api_key` at construction, and nothing downstream carries account
context, so **no inference call has ever presented a per-account key** (BILL-01).

ADR-0003 recorded the decision to leave it that way and said why: it cannot bind on the
OpenAI/Anthropic fallbacks, and a key is not a containment layer if a request can leave
it. ADR-0004 then moved containment to a dollar ceiling that holds whichever provider
served the call, which is what turns this from *the only thing between an account and an
unbounded bill* into an **additive** change whose value is provider-side attribution
per customer — and a second belt on the OpenRouter path specifically.

**What this must NOT do**, and each is guarded below:

- Claim to bind where it cannot. A request that falls back to OpenAI or Anthropic
  carries the operator key, because there is no other key to carry; the disclosure
  already required for a fallback now names that too.
- Cost a database round trip per LLM call. The key is resolved once per request.
- Fail a request because the key could not be resolved. An account with no provisioned
  key, an unreadable ciphertext, or a lookup that raises all fall back to the operator
  key — the spend is bounded by the dollar ceiling either way, and refusing here would
  turn an attribution feature into an outage.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


class TestTheAdapterPresentsTheKeyItIsGiven:
    async def test_a_per_request_key_overrides_the_operator_key(self) -> None:
        from app.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter()
        seen: dict[str, Any] = {}

        async def _capture(url: str, **kwargs: Any) -> Any:
            seen.update(kwargs)
            raise RuntimeError("stop here — the headers are the measurement")

        with patch.object(adapter._client, "post", new=_capture), pytest.raises(Exception):
            await adapter.complete([], api_key="sk-or-account")

        auth = (seen.get("headers") or {}).get("Authorization")
        assert auth == "Bearer sk-or-account", (
            "the adapter bound `settings.openrouter_api_key` at construction and had no "
            "way to present anything else, so a minted per-account key was never used "
            "on an inference call (BILL-01)"
        )

    async def test_without_one_the_operator_key_is_used(self) -> None:
        """The default path must not change: most deployments have no account keys."""
        from app.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter()
        seen: dict[str, Any] = {}

        async def _capture(url: str, **kwargs: Any) -> Any:
            seen.update(kwargs)
            raise RuntimeError("stop")

        with patch.object(adapter._client, "post", new=_capture), pytest.raises(Exception):
            await adapter.complete([])

        assert not (seen.get("headers") or {}).get("Authorization"), (
            "with no per-request key the client's own header must serve, or every "
            "deployment without account keys gets a header built from nothing"
        )


class TestTheRouterCarriesAccountContext:
    async def test_the_key_reaches_openrouter(self) -> None:
        from app.llm.router import LLMRouter

        router = LLMRouter(account_openrouter_key="sk-or-account")
        provider = _FakeProvider()
        router._instances["openrouter"] = provider

        with patch.object(router, "_get_fallback_chain", return_value=["openrouter"]):
            await router.complete([], model="deepseek/deepseek-v4-flash-0731")

        assert provider.calls[0]["api_key"] == "sk-or-account"

    async def test_it_is_not_offered_to_a_provider_that_cannot_use_it(self) -> None:
        """An OpenRouter key presented to OpenAI is a 401, not a fallback."""
        from app.llm.router import LLMRouter

        router = LLMRouter(account_openrouter_key="sk-or-account")
        provider = _FakeProvider(name="openai")
        router._instances["openai"] = provider

        with patch.object(router, "_get_fallback_chain", return_value=["openai"]):
            await router.complete([], model="gpt-4o")

        assert "api_key" not in provider.calls[0]

    async def test_no_account_key_leaves_every_call_unchanged(self) -> None:
        from app.llm.router import LLMRouter

        router = LLMRouter()
        provider = _FakeProvider()
        router._instances["openrouter"] = provider

        with patch.object(router, "_get_fallback_chain", return_value=["openrouter"]):
            await router.complete([], model="x/y")

        assert "api_key" not in provider.calls[0], (
            "a deployment with no per-account keys must send exactly what it sent before"
        )

    async def test_a_fallback_away_from_openrouter_is_disclosed_as_leaving_the_key(
        self, caplog
    ) -> None:
        """The honest half: the account's ceiling does not travel with the request."""
        from app.llm.router import LLMRouter

        router = LLMRouter(account_openrouter_key="sk-or-account")
        with caplog.at_level("WARNING", logger="app.llm.router"):
            router._disclose_fallback("openrouter", "openai")
        line = " ".join(r.getMessage() for r in caplog.records)
        assert "account" in line.lower(), (
            "a request that leaves OpenRouter carries the OPERATOR key — there is no "
            "other key to carry — so the account's own ceiling stops applying to it. "
            f"Nothing said so: {line!r}"
        )


class TestResolvingTheKeyCannotBreakARequest:
    async def test_an_unprovisioned_account_resolves_to_none(self) -> None:
        from app.services.openrouter_credit_service import resolve_account_key

        db = AsyncMock()
        with patch(
            "app.services.openrouter_credit_service.OpenRouterCreditService._row",
            new=AsyncMock(return_value=_Row(key_encrypted=None, key_hash=None)),
        ):
            assert await resolve_account_key(db, "u1") is None

    async def test_an_unreadable_ciphertext_resolves_to_none(self) -> None:
        """Fernet raises on a key from a previous `MASTER_ENCRYPTION_KEY`."""
        from app.services.openrouter_credit_service import resolve_account_key

        db = AsyncMock()
        with (
            patch(
                "app.services.openrouter_credit_service.OpenRouterCreditService._row",
                new=AsyncMock(return_value=_Row(key_encrypted="garbage", key_hash="h")),
            ),
            patch(
                "app.services.openrouter_credit_service.decrypt",
                side_effect=ValueError("bad token"),
            ),
        ):
            assert await resolve_account_key(db, "u1") is None

    async def test_a_lookup_that_raises_resolves_to_none(self) -> None:
        from app.services.openrouter_credit_service import resolve_account_key

        db = AsyncMock()
        with patch(
            "app.services.openrouter_credit_service.OpenRouterCreditService._row",
            new=AsyncMock(side_effect=RuntimeError("db is down")),
        ):
            assert await resolve_account_key(db, "u1") is None, (
                "refusing a request because an attribution key could not be read turns "
                "a reporting feature into an outage; the dollar ceiling bounds the "
                "spend either way (ADR-0004)"
            )

    async def test_the_key_is_resolved_once_per_request_not_per_call(self) -> None:
        """A database round trip per LLM call is not what attribution is worth."""
        from app.llm.router import LLMRouter

        router = LLMRouter(account_openrouter_key="sk-or-account")
        provider = _FakeProvider()
        router._instances["openrouter"] = provider

        with patch.object(router, "_get_fallback_chain", return_value=["openrouter"]):
            for _ in range(3):
                await router.complete([], model="x/y")

        assert len(provider.calls) == 3
        assert all(c["api_key"] == "sk-or-account" for c in provider.calls)


class _Row:
    def __init__(self, *, key_encrypted: str | None, key_hash: str | None) -> None:
        self.key_encrypted = key_encrypted
        self.key_hash = key_hash


class _FakeProvider:
    def __init__(self, name: str = "openrouter") -> None:
        self._name = name
        self.calls: list[dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return self._name

    async def complete(self, messages, **kwargs: Any):  # noqa: ANN001
        self.calls.append(kwargs)
        from app.llm.base import LLMResponse

        return LLMResponse(
            content="ok",
            tool_calls=[],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            provider=self._name,
            model=kwargs.get("model") or "m",
        )


class TestTheRequestScopedKey:
    """The chat path builds `ConversationalAgent()` at MODULE level, so one router and
    one set of adapters serve every request in the process. A constructor argument
    cannot reach it; a `ContextVar` can, which is how the MCP principal and the
    workflow id already travel."""

    async def test_the_shared_router_picks_up_the_current_account(self) -> None:
        from app.llm.account_key import account_key_scope
        from app.llm.router import LLMRouter

        shared = LLMRouter()  # built once, as `chat.py` does
        provider = _FakeProvider()
        shared._instances["openrouter"] = provider

        with (
            patch.object(shared, "_get_fallback_chain", return_value=["openrouter"]),
            account_key_scope("sk-or-alice"),
        ):
            await shared.complete([], model="x/y")

        assert provider.calls[0]["api_key"] == "sk-or-alice"

    async def test_the_scope_restores_what_it_replaced(self) -> None:
        """A key left behind is the PREVIOUS customer's, in the process serving the next."""
        from app.llm.account_key import account_key_scope, current_account_openrouter_key

        assert current_account_openrouter_key.get() is None
        with account_key_scope("sk-or-alice"):
            assert current_account_openrouter_key.get() == "sk-or-alice"
            with account_key_scope("sk-or-bob"):
                assert current_account_openrouter_key.get() == "sk-or-bob"
            assert current_account_openrouter_key.get() == "sk-or-alice", (
                "the inner scope cleared instead of restoring, leaving the outer "
                "request keyless for the rest of its work"
            )
        assert current_account_openrouter_key.get() is None

    async def test_an_exception_still_unbinds(self) -> None:
        from app.llm.account_key import account_key_scope, current_account_openrouter_key

        with pytest.raises(RuntimeError), account_key_scope("sk-or-alice"):
            raise RuntimeError("the request failed")
        assert current_account_openrouter_key.get() is None, (
            "a failed request left its key bound for whoever the process served next"
        )

    async def test_a_constructor_key_outranks_the_context(self) -> None:
        """The background indexing routers pass theirs explicitly and must keep it."""
        from app.llm.account_key import account_key_scope
        from app.llm.router import LLMRouter

        router = LLMRouter(account_openrouter_key="sk-or-explicit")
        provider = _FakeProvider()
        router._instances["openrouter"] = provider

        with (
            patch.object(router, "_get_fallback_chain", return_value=["openrouter"]),
            account_key_scope("sk-or-ambient"),
        ):
            await router.complete([], model="x/y")

        assert provider.calls[0]["api_key"] == "sk-or-explicit"

    async def test_binding_is_skipped_without_a_user(self) -> None:
        from app.llm.account_key import bind_account_key

        assert await bind_account_key(AsyncMock(), None) is None


class TestTheChatPathBindsIt:
    """A key nothing passes is the defect this closes, not a smaller version of it."""

    def test_the_binding_helper_pairs_the_scope(self) -> None:
        """The unbind must be structural, not a second statement somebody can forget."""
        import inspect

        from app.api.routes.chat import _run_with_account_key

        source = inspect.getsource(_run_with_account_key)
        assert "account_key_scope" in source and ".set(" not in source, (
            "a bare `set()` leaves the key bound when the run raises, and that key is "
            "the previous customer's in the process serving the next one"
        )

    def test_every_chat_transport_binds_it(self) -> None:
        """REST, SSE and WebSocket answer the same questions and spend the same money.

        Read from the AST rather than from a substring over the module, because the
        first draft searched the whole file and passed as soon as ONE transport was
        wired — and there are three.
        """
        import ast
        import inspect

        from app.api.routes import chat as chat_mod

        tree = ast.parse(inspect.getsource(chat_mod))
        bound = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and "_run_with_account_key" in ast.unparse(node)
            and "bind_account_key" in ast.unparse(node)
        }
        for entry in ("ask", "ask_stream", "chat_websocket"):
            assert entry in bound, (
                f"{entry} runs the agent without binding the account's key, so it "
                "spends the customer's money on the operator account (BILL-01)"
            )
