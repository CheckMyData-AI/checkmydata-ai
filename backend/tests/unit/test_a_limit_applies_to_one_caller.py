"""Every rate limit in the product was shared by everybody.

P2 row 17; API-05 and API-06.

**API-05 — the key is the router's address, not the caller's.** `Limiter` is built
with slowapi's `get_remote_address`, which returns `request.client.host` verbatim.
Uvicorn only rewrites that from `X-Forwarded-For` when the peer is in
`forwarded_allow_ips`, which defaults to `127.0.0.1`; the container CMD passes neither
`--proxy-headers` nor a trusted list, and `FORWARDED_ALLOW_IPS` appears nowhere in the
repository. Behind Heroku's router every request therefore presents the same host — so
`POST /api/auth/register` at `5/minute` means the sixth registration *anywhere in the
world* in a given minute gets a 429, and `/api/chat/ask` at `20/minute` is a global
twenty across the entire tenant base. The documented contract ("per IP") is true of
neither the IP nor the user.

Trusting `X-Forwarded-For` outright is the *other* wrong answer — it is a header the
caller writes. The key is the authenticated user where there is one, and otherwise the
address a **counted** number of trusted hops in from the right-hand end of the chain.

**API-06 — one status, two wire shapes.** `API.md` states every error is
`{"detail": …}`. The handler-raised 429s are; the rate limiter's is
`{"error": "Rate limit exceeded: 20 per 1 minute"}` with no `detail` key at all — and
the same status also carries token-budget exhaustion, which is not retryable and
resets tomorrow, not in a moment.
"""

from __future__ import annotations

import pytest


class _Req:
    """The two things a key function reads."""

    def __init__(self, *, host: str, headers: dict[str, str] | None = None, cookies=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}
        self.cookies = cookies or {}


class TestTheKeyIdentifiesTheCaller:
    """API-05."""

    def test_two_callers_behind_one_proxy_get_different_keys(self) -> None:
        from app.core.rate_limit import client_identifier

        a = _Req(host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.7"})
        b = _Req(host="10.0.0.1", headers={"x-forwarded-for": "198.51.100.4"})

        assert client_identifier(a) != client_identifier(b), (
            "both requests present the router's address, so every limit in the "
            "product is one shared counter: the sixth registration attempt anywhere "
            "in the world in a minute gets a 429, and /api/chat/ask at 20/minute is "
            "twenty across the whole tenant base (API-05)"
        )

    def test_a_forged_header_cannot_mint_new_keys(self) -> None:
        """The counted hop is the whole difference between this and trusting XFF.

        With one trusted proxy, only the right-most entry was written by something
        we control. Everything to its left is whatever the caller sent, so a client
        appending twenty fake addresses must not get twenty buckets.
        """
        from app.core.rate_limit import client_identifier

        forged = _Req(
            host="10.0.0.1",
            headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.7"},
        )
        also_forged = _Req(
            host="10.0.0.1",
            headers={"x-forwarded-for": "9.9.9.9, 203.0.113.7"},
        )
        assert client_identifier(forged) == client_identifier(also_forged), (
            "the key is taken from an attacker-controlled position in the chain, so "
            "one caller can mint an unlimited number of rate-limit buckets"
        )

    def test_an_authenticated_caller_is_keyed_on_the_user(self) -> None:
        """Two people on one office NAT are two callers."""
        from app.core.rate_limit import client_identifier
        from app.services.auth_service import AuthService

        auth = AuthService()
        one = auth.create_token("user-one", "one@example.com")
        two = auth.create_token("user-two", "two@example.com")

        a = _Req(host="10.0.0.1", headers={"authorization": f"Bearer {one}"})
        b = _Req(host="10.0.0.1", headers={"authorization": f"Bearer {two}"})

        assert client_identifier(a) != client_identifier(b)
        assert "user-one" in client_identifier(a)

    def test_a_junk_token_falls_back_to_the_address(self) -> None:
        from app.core.rate_limit import client_identifier

        junk = _Req(
            host="10.0.0.1",
            headers={"authorization": "Bearer not-a-jwt", "x-forwarded-for": "203.0.113.7"},
        )
        assert "203.0.113.7" in client_identifier(junk), (
            "an unparseable token must not collapse every anonymous caller onto one "
            "key — that is the defect this whole row is about, arriving by a new route"
        )

    def test_the_trusted_hop_count_is_configurable(self) -> None:
        from app.config import Settings

        assert Settings().trusted_proxy_hops >= 0


class TestA429SaysWhichKind:
    """API-06."""

    @pytest.mark.asyncio
    async def test_the_limiter_speaks_the_documented_envelope(self) -> None:
        import json

        from slowapi.errors import RateLimitExceeded

        from app.core.rate_limit import rate_limit_exceeded_handler

        class _Limit:
            error_message = None
            limit = type("L", (), {"error_message": None})()

        exc = RateLimitExceeded(_Limit())
        response = rate_limit_exceeded_handler(_Req(host="1.2.3.4"), exc)

        body = json.loads(bytes(response.body))
        assert "detail" in body, (
            "API.md states every error is {'detail': …}. slowapi emits "
            f"{{'error': …}} with no detail key at all: {body}. Two wire shapes share "
            "one status, and the frontend reads `detail` (API-06)"
        )
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_it_says_it_is_retryable(self) -> None:
        import json

        from slowapi.errors import RateLimitExceeded

        from app.core.rate_limit import rate_limit_exceeded_handler

        class _Limit:
            error_message = None
            limit = type("L", (), {"error_message": None})()

        response = rate_limit_exceeded_handler(_Req(host="1.2.3.4"), RateLimitExceeded(_Limit()))
        body = json.loads(bytes(response.body))
        assert body.get("error_type") == "rate_limit", (
            "the same 429 also carries token-budget exhaustion, which resets tomorrow "
            "rather than in a moment — and nothing on the wire distinguishes them, so "
            "the frontend tells a user whose monthly budget is spent to wait a moment "
            "(API-06)"
        )
