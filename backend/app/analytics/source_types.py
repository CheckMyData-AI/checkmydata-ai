"""The one definition of "this connection is an analytics vendor" (T14).

Membership in :data:`ANALYTICS_SOURCE_TYPES` is what four unrelated subsystems
gate on — the hourly collect wave (:mod:`app.main`), the collect service, the
orchestrator's tool availability (via
:meth:`~app.agents.context_loader.ContextLoader.has_analytics_sources`) and the
tool dispatcher's connection resolution. It used to be spelled out twice, once
per side of that split; adding a vendor to one copy would have left the other
half of the system unable to see connections the first half happily created.

This module exists rather than the constant living in
:mod:`app.services.analytics_collect_service` because that module imports the
GA4 adapter and the Google API client libraries. The tool-definition module and
the orchestrator's per-request capability probe need the *name* of the vendor
family, not the machinery to talk to it, and making them pay that import (and
risk a cycle back through the agent package) is the reason the second copy was
written in the first place. Nothing but the standard library may be imported
here — a test enforces it.

A tuple, not a set: the values reach SQLAlchemy's ``Column.in_()`` in the cron
dispatcher, which documents a sequence, and a fixed order keeps generated
``IN`` lists and log lines reproducible. Three items make membership cost
nothing either way.
"""

from __future__ import annotations

#: ``Connection.source_type`` values served by the analytics agent.
#: ``appstore``/``googleplay`` are reserved for m1/m2; they are listed here
#: because connection *gating* is vendor-agnostic — the agent itself refuses a
#: vendor it has no report catalogue for, with a message that says which.
ANALYTICS_SOURCE_TYPES: tuple[str, ...] = ("ga4", "appstore", "googleplay")


#: Bounds on a connection's `source_config.backfill_days`, applied on the SERVER.
#:
#: ANA-06: `source_config` is an unvalidated free-form dict on both `ConnectionCreate`
#: and `ConnectionUpdate`; `GA4Config.from_mapping` rejects only non-positive values and
#: `_backfill_days` only falls back on a non-number. The clamp the runbook promises —
#: `safeInt(analyticsForm.backfill_days, 30, 1, 3650)` — is in the React form, which any
#: direct API call bypasses. `{"backfill_days": 100000}` was accepted, and every run
#: then enumerated 100 000 daily periods per report (500 000 vendor calls) beginning in
#: **1752**, while `GET /collection-status` rebuilt the same 500 000 period strings on
#: a read-only endpoint.
#:
#: The numbers are the form's own, deliberately: a server bound that disagrees with the
#: control the user is looking at produces a refusal they cannot act on. Ten years is
#: past any vendor's retention — GA4 keeps 14 months of the data this collects.
MIN_BACKFILL_DAYS = 1
MAX_BACKFILL_DAYS = 3650


def clamp_backfill_days(value: object) -> int | None:
    """Bound *value* to [MIN, MAX], or return ``None`` when it is not a window at all.

    ``None`` for a missing or unreadable value rather than a default: absent is not out
    of range, and substituting a number here would override the caller's own default
    (`analytics_backfill_days`, or a vendor config's) with this module's opinion.
    """
    # `bool` before `int`, because `True` IS an int in Python and a window of one day
    # is not what `backfill_days: true` meant.
    if value is None or isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return max(MIN_BACKFILL_DAYS, min(MAX_BACKFILL_DAYS, days))


def validated_timezone(value: object) -> str | None:
    """The IANA zone in *value*, or ``None`` when it names none. Raises on a wrong one.

    One definition, because the zone is written in two places and only one of them
    used to check it: the connection form's `source_config` (a direct API call goes
    nowhere near `GA4Config`) and the config parser the collector reads. A zone that
    cannot be resolved must not be stored — it degrades to the scheduler's clock, which
    is the A-04 defect the knob exists to close, and it does so silently.

    Raises:
        ValueError: *value* is a non-empty string that is not an IANA zone name.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if value is None:
        return None
    zone = str(value).strip()
    if not zone:
        return None
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError(
            f"property_timezone {zone!r} is not an IANA timezone name "
            "(e.g. 'America/Los_Angeles'). An abbreviation or a UTC offset names no "
            "place, so it cannot say when a day ends there."
        ) from exc
    return zone


def validated_currency_code(value: object) -> str | None:
    """The upper-cased ISO-4217 code in *value*, or ``None``. Raises on a wrong one.

    Shape only — the list of live codes belongs to the vendor, not to this repository.
    Refused rather than dropped: GA4 answers a bad `currencyCode` with a 400, which the
    taxonomy reads as *invalid-request* and does not retry, so the connection would fail
    every period of every night with the cause three layers from where it was typed.
    """
    if value is None:
        return None
    code = str(value).strip().upper()
    if not code:
        return None
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"currency_code {code!r} is not a three-letter ISO-4217 code (e.g. 'USD')")
    return code
