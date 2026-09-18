"""Does the vendor still accept this credential? (PRJ-10)

A credential is created once and used every night by a background job, so the first
sign that a key was revoked, deleted or had its service account disabled is a report
that stopped arriving — days later, in a log nobody is reading. A-02 made that failure
*legible* once it happens; this makes it **askable** before it does.

The question is deliberately narrower than a connection's ``test_connection``: it is
"does the vendor still issue a token for this key", not "can it read property 294380179".
A credential has no property — the connection does — and a probe that needs one could
not answer for a credential that is not attached to anything yet, which is exactly the
moment a person wants to know whether the JSON they pasted is the right one.
"""

from __future__ import annotations

import asyncio
import logging

from app.analytics.errors import AnalyticsAuthError, AnalyticsError, AnalyticsTransientError
from app.analytics.source_types import ANALYTICS_SOURCE_TYPES

logger = logging.getLogger(__name__)

#: Providers whose credential can actually be probed. The other members of the vendor
#: family are reserved for m1/m2 and have no client to ask.
VERIFIABLE_PROVIDERS: tuple[str, ...] = ("ga4",)


async def verify_vendor_secret(provider: str, secret: str) -> None:
    """Return normally when the vendor accepts *secret*; raise when it does not.

    Raises:
        AnalyticsAuthError: the credential is malformed, revoked or refused.
        AnalyticsTransientError: the vendor could not be reached — which is **not**
            evidence against the key, and the caller must not record it as one.
        AnalyticsError: this provider has no probe.
    """
    if provider not in ANALYTICS_SOURCE_TYPES:
        raise AnalyticsError(f"{provider!r} is not an analytics vendor")
    if provider not in VERIFIABLE_PROVIDERS:
        raise AnalyticsError(
            f"{provider} credentials cannot be checked yet — no collector exists for them"
        )
    await _verify_ga4(secret)


async def _verify_ga4(secret: str) -> None:
    """One real token refresh, off the loop (`refresh` is a blocking HTTP call).

    A refresh is what distinguishes a dead key from a vendor hiccup: a revoked or
    deleted service-account key comes back through gRPC's metadata plugin as a 500,
    which every other probe reads as "the vendor is having a moment" (A-02).
    """
    from app.analytics.ga4.config import GA4Credentials

    credentials = GA4Credentials.from_json(secret)
    try:
        from google.auth.transport.requests import Request as AuthRequest
    except ImportError as exc:  # pragma: no cover - google-auth absent in a trimmed image
        raise AnalyticsTransientError(
            "google-auth is not installed in this runtime, so the key cannot be checked"
        ) from exc

    from app.analytics.ga4.adapter import _is_auth_failure

    try:
        creds = credentials.build_credentials()
        await asyncio.to_thread(creds.refresh, AuthRequest())
    except AnalyticsError:
        raise
    except Exception as exc:
        if _is_auth_failure(exc):
            raise AnalyticsAuthError(f"Google rejected this key: {exc}") from exc
        raise AnalyticsTransientError(f"Google could not be reached: {exc}") from exc
