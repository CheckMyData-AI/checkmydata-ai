"""Rate limiting configuration using slowapi.

With ``REDIS_URL`` set (and the ``redis`` package installed) slowapi counts
against Redis so limits hold across processes/dynos (T-SEC-7). Otherwise it
falls back to per-process in-memory counting.
"""

import importlib.util
import logging
from typing import Any

from fastapi.responses import JSONResponse
from slowapi import Limiter

from app.config import settings
from app.core.auth_cookies import SESSION_COOKIE
from app.core.redis_tls import redis_connect_kwargs

logger = logging.getLogger(__name__)


def _storage_uri() -> str:
    if settings.redis_url:
        if importlib.util.find_spec("redis") is not None:
            return settings.redis_url
        logger.warning(
            "REDIS_URL is set but the 'redis' package is not installed; "
            "rate limits fall back to per-process memory storage"
        )
    return "memory://"


def _storage_options() -> dict[str, str]:
    """TLS kwargs for Heroku ``rediss://`` (self-signed chain)."""
    if not settings.redis_url:
        return {}
    opts = redis_connect_kwargs(settings.redis_url)
    return {k: str(v) for k, v in opts.items()}


def _client_address(request: Any) -> str:
    """The caller's address, counting trusted hops in from the right (API-05).

    slowapi's `get_remote_address` returns `request.client.host` verbatim, and
    uvicorn only rewrites that from `X-Forwarded-For` when the peer is in
    `forwarded_allow_ips` — which defaults to `127.0.0.1`, while the container CMD
    passes neither `--proxy-headers` nor a trusted list. Behind a platform router
    every request therefore presented the SAME host, and every limit in the product
    was one shared counter.

    Trusting the header outright is the other wrong answer: the caller writes it, so
    `X-Forwarded-For: <random>` would mint an unlimited number of buckets. The entries
    a caller can forge are the LEFT-hand ones — each proxy appends what it saw — so
    with `trusted_proxy_hops = 1` the right-most entry is the only one written by
    something we control, and that is the one taken.

    `0` hops means no proxy: the peer address is the caller and the header is ignored
    entirely. That is the correct setting for a direct-to-internet deployment, and it
    fails CLOSED — over-counting a shared address, never under-counting a forged one.
    """
    peer = getattr(getattr(request, "client", None), "host", None) or "unknown"
    hops = max(0, int(settings.trusted_proxy_hops))
    if hops == 0:
        return peer
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if not forwarded:
        return peer
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return peer
    # Index from the right: `hops` proxies appended `hops` entries, and the client
    # address the outermost trusted proxy observed is `chain[-hops]`. A chain shorter
    # than the configured trust is a misconfiguration or a stripped header, and the
    # left-most entry is the closest thing to the caller that exists.
    return chain[-hops] if len(chain) >= hops else chain[0]


def client_identifier(request: Any) -> str:
    """What a rate limit counts against: the user when known, else the address.

    Keying on the address alone is wrong in both directions — two colleagues behind
    one office NAT share a bucket, and one person on two networks gets two. The token
    is already on the request for every authenticated route, and reading its subject
    costs a signature check and no database round trip.

    An absent or unparseable token falls back to the address rather than to a
    constant: collapsing every anonymous caller onto one key is the defect this
    function exists to remove, and it must not come back through the error path.
    """
    token: str | None = None
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    else:
        token = request.cookies.get(SESSION_COOKIE)

    if token:
        from app.services.auth_service import AuthService

        # No wrapper: `decode_token` catches `JWTError` itself and returns None for
        # anything unparseable or expired, which is an ordinary event on a public
        # route. Catching again would only hide a defect in this function.
        payload = AuthService().decode_token(token)
        subject = (payload or {}).get("sub")
        if subject:
            return f"user:{subject}"

    return f"ip:{_client_address(request)}"


limiter = Limiter(
    key_func=client_identifier,
    default_limits=["60/minute"],
    storage_uri=_storage_uri(),
    storage_options=_storage_options(),
)


def rate_limit_exceeded_handler(request: Any, exc: Exception) -> JSONResponse:
    """A 429 in the envelope `API.md` documents, saying which kind it is (API-06).

    slowapi's own handler emits ``{"error": "Rate limit exceeded: 20 per 1 minute"}``
    — no ``detail`` key — while `API.md` states every error is ``{"detail": …}`` and
    the frontend reads exactly that. The same status also carries token-budget
    exhaustion, which resets tomorrow rather than in a moment, so `error_type` is what
    lets a client tell "wait" from "upgrade" instead of guessing from the status.
    """
    limit = getattr(exc, "limit", None)
    described = getattr(limit, "error_message", None) or str(getattr(exc, "detail", "") or "")
    detail = f"Rate limit exceeded: {described}" if described else "Rate limit exceeded"
    headers: dict[str, str] = {}
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers["Retry-After"] = str(int(retry_after))
    return JSONResponse(
        {"detail": detail, "error_type": "rate_limit", "is_retryable": True},
        status_code=429,
        headers=headers,
    )
