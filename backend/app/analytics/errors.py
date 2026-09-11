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
    — a payload the parser cannot use, say. Not retryable. An *invalid request*
    is no longer one of these: see :class:`AnalyticsInvalidRequestError`.
    """


class AnalyticsInvalidRequestError(AnalyticsError):
    """400 / 404 — the request itself can never succeed as written.

    A configuration error, in the same family as auth and permission: a property
    id that does not exist, a metric GA4 has retired, a dimension renamed under
    the report. Repeating it costs quota and cannot work, so the collector stops
    the whole report rather than isolating the period — the reasoning the runbook
    already gives for 401/403 applies to these word for word.

    Kept apart from :class:`AnalyticsEmpty` deliberately. 404 used to map there,
    and ``empty`` is a *done* status: a deleted property recorded every period as
    "collected, and it was zero", never returned to the pending set, and reported
    the connection healthy while the agent answered over a fabricated zero.
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
    """A 2xx response that carried no rows — and *only* that.

    Not a failure of the run: the period is journalled as ``empty`` and is not
    retried, so a genuinely quiet day never becomes an infinite refetch loop.

    That "not retried" is precisely why the meaning has to stay narrow. The class
    is a claim that the vendor answered and had nothing to say; a 404 is the
    vendor saying the question was wrong, and recording one as the other makes a
    misconfiguration permanent and invisible.
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
