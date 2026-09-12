"""Entitlement provider registry.

The product asks :func:`get_entitlements`; what answers depends on what is installed. The
open-source build gets :class:`UnlimitedEntitlements` and never reaches for a Stripe key;
the cloud image registers its own provider at start-up.

Deliberately a registry rather than an import: the product must not name the commercial
package, or the package is not separable.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.entitlements.base import Entitlements, QuotaExceededError
from app.entitlements.unlimited import UnlimitedEntitlements

__all__ = [
    "Entitlements",
    "QuotaExceededError",
    "UnlimitedEntitlements",
    "get_entitlements",
    "index_quota_bytes",
    "may_run_scheduled_work",
    "seat_limit",
    "reset_entitlements",
    "set_entitlements",
]

logger = logging.getLogger(__name__)

#: A one-slot holder rather than a module `global`. The two PLW0603 suppressions the
#: `global` form needed bought nothing, and the suppression ratchet asking whether they
#: were worth recording was the right prompt: the honest answer was to remove the need.
_slot: dict[str, Entitlements] = {}


def set_entitlements(provider: Entitlements) -> None:
    """Install a provider. Called once, by the cloud package, at start-up."""
    _slot["provider"] = provider


def reset_entitlements() -> None:
    """Drop back to the permissive default. For tests, and for a cloud image that has
    lost its billing configuration and should degrade to working rather than to broken."""
    _slot.pop("provider", None)


def get_entitlements() -> Entitlements:
    return _slot.get("provider") or UnlimitedEntitlements()


async def may_run_scheduled_work(db: AsyncSession, user_id: str) -> bool:
    """May this account's work run unattended? Ask here, never a provider directly.

    Two things this function exists for, and neither is delegation.

    **A provider may predate the question.** The whole point of `Entitlements` being a
    structural `Protocol` is that the private cloud package satisfies it without
    importing this repository — so a package built against the three-method surface has
    no fourth method, and `getattr` is the only honest way to ask. When it cannot answer,
    the answer is **yes**, for the reason `reset_entitlements` already gives: an image
    that has lost part of its billing configuration degrades to working, not to broken.
    An unmetered night is recoverable and visible in the usage table; a paying customer
    whose nightly sync stopped without a word is the failure nobody notices for a week.

    **A provider may fail.** A billing lookup that raises must not take the cron down
    with it, and it must not silently withhold the work either — so it is logged and
    allowed, the same direction as above.
    """
    provider = get_entitlements()
    ask = getattr(provider, "may_run_scheduled_work", None)
    if ask is None:
        logger.debug(
            "entitlements: %s cannot answer may_run_scheduled_work; allowing",
            type(provider).__name__,
        )
        return True
    try:
        return bool(await ask(db, user_id))
    except Exception:
        logger.warning(
            "entitlements: could not check whether %s may run scheduled work; allowing",
            user_id[:8],
            exc_info=True,
        )
        return True


async def index_quota_bytes(db: AsyncSession, user_id: str) -> int:
    """Bytes of index this account's plan allows per project; ``0`` means unlimited.

    A **module helper rather than a fifth protocol method**, and that is the decision
    rather than a shortcut. `Entitlements` has four methods and its guard demands a
    written argument for another; the argument for `may_run_scheduled_work` was that a
    capability could not be expressed by any of the three ceilings. This is not that. D5
    chose to WARN rather than block, and a warning does not ask permission — it reads a
    number the plan already publishes. Widening a protocol whose whole point is that a
    private package satisfies it without importing this repository, in order to read a
    number, is a cost with nothing on the other side of it.

    Degrades **open**, in the same direction and for the same reason as
    `may_run_scheduled_work`: a provider that predates the question, or one whose lookup
    raises, yields ``0`` — unlimited, therefore no warning. A billing outage must not put
    "you are over quota" on a paying customer's rail, where they cannot check it and
    cannot act on it.
    """
    provider = get_entitlements()
    ask = getattr(provider, "get_entitlements", None)
    if ask is None:
        logger.debug(
            "entitlements: %s cannot answer index_quota_bytes; treating as unlimited",
            type(provider).__name__,
        )
        return 0
    try:
        ent = await ask(db, user_id)
        return int(getattr(ent, "max_index_bytes", 0) or 0)
    except Exception:
        logger.warning(
            "entitlements: index_quota lookup failed for %s; treating as unlimited",
            user_id[:8] if user_id else "?",
            exc_info=True,
        )
        return 0


async def seat_limit(db: AsyncSession, user_id: str) -> int:
    """How many members this account's plan allows per project; ``0`` is unlimited.

    Shaped exactly like :func:`index_quota_bytes`, and for the same reason: reading a
    number the plan already publishes is not a fifth capability question, and the
    protocol's whole point is that a private package satisfies it without importing
    this repository.

    Degrades **open** — a provider that predates the question, or a lookup that
    raises, yields ``0``. A billing outage must not stop a team adding the colleague
    they are already paying for.

    Note the asymmetry this makes visible: `_no_plan()` returns ``seats=1`` while
    every other zero in that same function means unlimited (BILL-09). That is
    deliberate and stays — an account with no subscription is the one case where a
    single seat is the honest answer — but it is the reason a caller must compare
    against the limit rather than against "is it zero".
    """
    provider = get_entitlements()
    ask = getattr(provider, "get_entitlements", None)
    if ask is None:
        logger.debug(
            "entitlements: %s cannot answer seat_limit; treating as unlimited",
            type(provider).__name__,
        )
        return 0
    try:
        ent = await ask(db, user_id)
        return int(getattr(ent, "seats", 0) or 0)
    except Exception:
        logger.warning(
            "entitlements: seat lookup failed for %s; treating as unlimited",
            user_id[:8] if user_id else "?",
            exc_info=True,
        )
        return 0
