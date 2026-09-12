"""Where a scheduled alert actually goes (COR-02).

`notification_channels` was accepted by the route, validated at 5 000 characters,
stored on the model and returned — and read by nothing. When an alert fired, the only
artifact was a `Notification` row behind the bell icon, which is an alerting feature
that can only alert people already looking at the product. Two code comments asserted
a mail delivery that did not exist, and the `EmailService` it would have needed has
been in the repository, in use for invites, the whole time.

Two rules shape this module, and both are refusals:

**An unknown channel is refused at the route, not ignored at delivery.** A parameter
that is accepted and silently does nothing is worse than one that is rejected: the
caller has no way to learn the difference between "configured" and "working".

**An email channel can only name a project member.** Without that, a stored field on
a row the customer controls would mail arbitrary addresses on a schedule — a spam
relay with the product's own sending domain behind it. The membership check is what
makes the feature safe to have at all, so it is not optional and not a setting.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

#: The channel kinds the product can actually deliver to. `in_app` is the
#: notification row that has always been written; `email:<address>` is the one this
#: module adds. A kind absent from here is refused when the schedule is saved.
IN_APP = "in_app"
EMAIL_PREFIX = "email:"

#: A ceiling on fan-out per alert. Not a performance bound — a stored list is
#: caller-controlled, and "how many messages can one row send" should have an answer.
MAX_EMAIL_RECIPIENTS = 10


def parse_channels(channels_json: str | None) -> list[str]:
    """The configured channels, or an empty list.

    Malformed JSON is an empty list rather than a raise: this is read on the delivery
    path, where the alert has already fired and refusing to deliver would lose it.
    Saving is where the shape is enforced — see :func:`validate_channels`.
    """
    if not channels_json:
        return []
    try:
        raw = json.loads(channels_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid notification_channels JSON: %s", channels_json[:200])
        return []
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str)]


def validate_channels(channels_json: str | None) -> None:
    """Raise ``ValueError`` if any channel names something undeliverable.

    Called when a schedule is created or updated. The whole point is that a caller
    who writes `"sms:+123"` learns it is not supported, instead of getting a 200 and
    silence at 03:00.
    """
    if not channels_json:
        return
    try:
        raw = json.loads(channels_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("notification_channels must be a JSON array of strings") from exc
    if not isinstance(raw, list):
        raise ValueError("notification_channels must be a JSON array of strings")
    for channel in raw:
        if not isinstance(channel, str):
            raise ValueError("notification_channels must be a JSON array of strings")
        if channel == IN_APP:
            continue
        if channel.startswith(EMAIL_PREFIX) and channel[len(EMAIL_PREFIX) :].strip():
            continue
        raise ValueError(
            f"unsupported notification channel {channel!r}; expected "
            f"{IN_APP!r} or 'email:<address>'"
        )


def resolve_email_recipients(
    channels_json: str | None, *, member_emails: Iterable[str]
) -> list[str]:
    """The addresses this alert may be mailed to.

    Restricted to *member_emails* — the people who can already read the project's
    data. An address outside that set is dropped and logged rather than raising: the
    membership that authorised it can be revoked after the schedule was saved, and
    that is a normal event, not a malformed configuration.
    """
    allowed = {e.strip().lower() for e in member_emails if e}
    out: list[str] = []
    for channel in parse_channels(channels_json):
        if not channel.startswith(EMAIL_PREFIX):
            continue
        address = channel[len(EMAIL_PREFIX) :].strip()
        if not address:
            continue
        if address.lower() not in allowed:
            logger.warning(
                "Alert email channel names %s, who is not a member of this project; skipping",
                address,
            )
            continue
        if address not in out:
            out.append(address)
    return out[:MAX_EMAIL_RECIPIENTS]


async def deliver_alert_emails(
    *,
    channels_json: str | None,
    member_emails: Iterable[str],
    schedule_title: str,
    project_name: str,
    messages: list[str],
) -> int:
    """Mail one alert to every member address the schedule names. Returns the count.

    Best-effort throughout: the notification row is written by the caller and is the
    durable record, so a mail failure must never turn a fired alert into a failed run.
    """
    recipients = resolve_email_recipients(channels_json, member_emails=member_emails)
    if not recipients or not messages:
        return 0
    try:
        from app.services.email_service import EmailService

        service = EmailService()
    except ImportError:
        # `resend` is an optional dependency in some builds; its absence means no
        # mail, not a failed run.
        logger.warning("Alert email delivery unavailable", exc_info=True)
        return 0

    sent = 0
    for address in recipients:
        # No wrapper here: `EmailService._send` catches and logs its own failures and
        # returns False — its class docstring says so verbatim ("Exceptions are caught
        # and logged so email failures never break the main flow"). Catching again
        # would only hide a defect in THIS function.
        if await service.send_alert_email(
            to_email=address,
            schedule_title=schedule_title,
            project_name=project_name,
            messages=messages,
        ):
            sent += 1
    return sent


async def deliver_for_schedule(session, schedule, alerts: list[dict]) -> None:
    """Mail a fired alert to the project members the schedule names.

    Lives here rather than beside either caller because both the cron loop and the
    run-now route need it, and `app.main` cannot be imported from a route module.

    Everything is best-effort: the notification row the caller has already written is
    the durable record, so nothing here may turn a fired alert into a failed run.
    """
    if not parse_channels(getattr(schedule, "notification_channels", None)):
        return
    try:
        from app.models.project import Project
        from app.services.membership_service import MembershipService

        members = await MembershipService().list_members(session, schedule.project_id)
        project = await session.get(Project, schedule.project_id)
        await deliver_alert_emails(
            channels_json=schedule.notification_channels,
            member_emails=[getattr(m.user, "email", "") for m in members],
            schedule_title=schedule.title,
            project_name=getattr(project, "name", "") or "your project",
            messages=[a.get("message", "") for a in alerts if a.get("message")],
        )
    except SQLAlchemyError:
        # The member and project lookups are the only things here that can fail on
        # their own; delivery below logs and swallows its own. A narrower clause so
        # a bug in this function surfaces instead of reading as a mail outage.
        logger.warning(
            "Alert email delivery failed for schedule %s", str(schedule.id)[:8], exc_info=True
        )
