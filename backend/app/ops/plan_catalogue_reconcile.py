"""Bring the `plans` table in line with the catalogue in code, at boot.

**Why this is not a migration.** A migration is a snapshot frozen at its revision; a price
list is a living value. The 2026-08-31 transition seeded `base` and `scale` with literals
inside `4f1a29a0e973`, which was correct then and becomes a second source of truth the
moment a tier is repriced — the code would say $900 while the row a customer resolves
against still said $199, and nothing would compare them. `app/services/plan_catalogue.py`
is the one home; this carries it to the database.

Same shape as `embedding_reconcile` and `encryption_reconcile`: idempotent, advisory-locked
so concurrent dynos do not both write, best-effort so a failure never blocks boot.

**Retired tiers are deactivated, never deleted.** A sold subscription may still reference
`pro`, and `EntitlementService.get_plan` deliberately does not filter on `is_active` so
that it keeps resolving. Deleting the row would strand it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.base import async_session_factory
from app.models.billing import Plan
from app.services.plan_catalogue import PAID_TIERS, RETIRED_TIER_IDS

logger = logging.getLogger(__name__)

# Stable, arbitrary 64-bit key for pg_try_advisory_xact_lock — never change it.
_ADVISORY_LOCK_KEY = 0x504C414E43415400


@dataclass
class CatalogueResult:
    status: str
    inserted: int = 0
    updated: int = 0
    retired: int = 0


async def reconcile_plan_catalogue(
    session_factory: async_sessionmaker | None = None,
) -> CatalogueResult:
    """Upsert every paid tier and deactivate the retired ones. Never raises."""
    factory = session_factory or async_session_factory
    inserted = updated = retired = 0
    try:
        async with factory() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                locked = await session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                if not locked:
                    return CatalogueResult("skipped_locked")

            existing = {p.id: p for p in (await session.scalars(select(Plan))).all()}

            for tier in PAID_TIERS:
                row = existing.get(tier["id"])
                if row is None:
                    session.add(Plan(**tier))
                    inserted += 1
                    continue
                changed = False
                for field, value in tier.items():
                    if field == "id":
                        continue
                    if getattr(row, field) != value:
                        setattr(row, field, value)
                        changed = True
                if changed:
                    updated += 1

            for slug in RETIRED_TIER_IDS:
                row = existing.get(slug)
                if row is not None and row.is_active:
                    row.is_active = False
                    retired += 1

            await session.commit()
    except Exception:
        logger.warning("reconcile_plan_catalogue failed; catalogue untouched", exc_info=True)
        return CatalogueResult("error")

    status = "unchanged" if not (inserted or updated or retired) else "reconciled"
    if status == "reconciled":
        logger.info(
            "Plan catalogue reconciled: %d inserted, %d updated, %d retired.",
            inserted,
            updated,
            retired,
        )
    return CatalogueResult(status, inserted=inserted, updated=updated, retired=retired)
