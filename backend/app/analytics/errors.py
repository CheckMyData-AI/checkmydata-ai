"""Typed errors for analytics vendor sources (spec §2.1, REQ-003).

The taxonomy exists so callers can tell a *configuration* failure (bad
credential, missing permission) from a *temporary* one (rate limit, 5xx,
network). Only the temporary kinds may be retried — retrying an auth or
permission failure burns vendor quota and can never succeed.
"""

from __future__ import annotations


class AnalyticsError(Exception):
    """Base class for every analytics-source failure.

    Raised directly only for failures that fit none of the sharper classes below
    (e.g. HTTP 400 — a malformed request). Not retryable.
    """


class AnalyticsAuthError(AnalyticsError):
    """401 — the credential is missing, malformed or expired.

    A configuration error: the user must fix the credential. Never retried.
    """


class AnalyticsPermissionError(AnalyticsError):
    """403 — the credential is valid but lacks access to the resource.

    Typically a GA4 property that was never shared with the service account.
    Never retried.
    """


# N818 (Error suffix) is waived deliberately: the name is fixed by spec §2.1 and
# the absence of "Error" is the point — an empty period is a normal outcome, not
# a failure. Renaming it would break every ``except AnalyticsEmpty`` downstream.
class AnalyticsEmpty(AnalyticsError):  # noqa: N818
    """404 / no data for the requested period.

    Not a failure of the run: the period is journalled as ``empty`` and is not
    retried, so a genuinely quiet day never becomes an infinite refetch loop.
    """


class QuotaExhaustedError(AnalyticsError):
    """The vendor's quota for this credential or property is exhausted.

    Retryable — the quota window rolls over — but the collection run records the
    period as failed so the outcome stays honest if it never recovers.
    """


class AnalyticsTransientError(AnalyticsError):
    """429 / 5xx / network — worth retrying with backoff."""


#: The only errors a retry loop may retry (spec §2.1). Kept next to the classes
#: so the policy cannot drift away from the taxonomy it describes.
RETRYABLE_ERRORS: tuple[type[AnalyticsError], ...] = (
    AnalyticsTransientError,
    QuotaExhaustedError,
)
