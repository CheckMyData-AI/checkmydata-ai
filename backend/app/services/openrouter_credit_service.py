"""Provision one OpenRouter key per account, and keep two pockets over its one counter.

Why the key rather than our own meter: `estimate_cost` reads an in-process cache of the
`/api/models` route, which the worker — where most LLM calls happen — can never populate,
so `estimated_cost_usd` was 0.00 on all 6 771 rows it had ever written. With a per-account
key, OpenRouter counts and we read. Our metering stays, for showing a customer their spend;
no money depends on it.

The provisioning API (`/api/v1/keys`) needs a **management** key, which is a higher
privilege than the inference key: it can mint keys that spend. It is read from settings and
never logged, and the open-source build never reaches this module at all.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.llm_credit import LlmCredit
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

_BASE = "https://openrouter.ai/api/v1/keys"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class CreditError(Exception):
    """Provisioning or top-up failed in a way the caller must not paper over."""


def _q(value: Decimal | float | int) -> Decimal:
    """Money, to six places. Credits are quoted in fractions of a cent by OpenRouter."""
    return Decimal(str(value)).quantize(Decimal("0.000001"))


class OpenRouterCreditService:
    """Key lifecycle plus the ledger arithmetic the key cannot express by itself."""

    def __init__(self, management_key: str | None = None) -> None:
        self._mgmt = management_key or settings.openrouter_management_key

    # ── HTTP ──────────────────────────────────────────────────────────────

    async def _call(self, method: str, path: str = "", **json) -> dict:
        if not self._mgmt:
            raise CreditError("OPENROUTER_MANAGEMENT_KEY is not configured")
        headers = {"Authorization": f"Bearer {self._mgmt}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method, f"{_BASE}{path}", headers=headers, json=json or None
            )
        if resp.status_code >= 400:
            # The body can echo the key on some error shapes; only the status is logged.
            raise CreditError(f"OpenRouter {method} {path or '/'} failed: {resp.status_code}")
        return resp.json().get("data", resp.json())

    # ── ledger ────────────────────────────────────────────────────────────

    async def _row(self, db: AsyncSession, user_id: str) -> LlmCredit:
        row = (
            await db.execute(select(LlmCredit).where(LlmCredit.user_id == user_id))
        ).scalar_one_or_none()
        if row is None:
            row = LlmCredit(user_id=user_id)
            db.add(row)
            await db.flush()
        return row

    @staticmethod
    def _split(spent: Decimal, included: Decimal) -> tuple[Decimal, Decimal]:
        """(from the included pocket, from the purchased pocket).

        Included first, always. Reversed, a customer who under-used their monthly
        allowance would lose credit they had paid for at every renewal.
        """
        from_included = min(spent, included)
        return from_included, max(Decimal(0), spent - included)

    async def _limit_for(self, row: LlmCredit, usage: Decimal) -> Decimal:
        """The ceiling to send OpenRouter: everything spent, plus both live pockets.

        Expressed against `usage` rather than as a running total, because OpenRouter's
        counter is monotonic and a ceiling below it would refuse every further call.
        """
        return _q(usage + _q(row.included_grant_usd) + _q(row.purchased_balance_usd))

    # ── operations ────────────────────────────────────────────────────────

    async def provision(self, db: AsyncSession, user_id: str, *, included_usd: float) -> str:
        """Create the account's key. Idempotent: an existing key is re-used, not replaced.

        Replacing it would orphan a key that is still authorised to spend, and OpenRouter
        does not let us list keys by our own account id to find it again.
        """
        row = await self._row(db, user_id)
        if row.key_encrypted and row.key_hash:
            return decrypt(row.key_encrypted)

        row.included_grant_usd = _q(included_usd)
        row.purchased_balance_usd = _q(row.purchased_balance_usd or 0)
        limit = _q(_q(included_usd) + _q(row.purchased_balance_usd))
        created = await self._call(
            "POST",
            name=f"checkmydata:{user_id}",
            limit=float(limit),
            # No reset. The limit is a lifetime ceiling and the pockets are ours to track;
            # a daily or monthly reset would hand OpenRouter a policy it cannot know.
            limit_reset=None,
        )
        key = created.get("key") or created.get("api_key")
        key_hash = created.get("hash") or created.get("id")
        if not key or not key_hash:
            raise CreditError("OpenRouter returned no key or hash")

        row.key_encrypted = encrypt(key)
        row.key_hash = key_hash
        row.usage_at_period_start = _q(0)
        row.provision_count = (row.provision_count or 0) + 1
        await db.commit()
        logger.info("credit: provisioned OpenRouter key for user=%s", user_id[:8])
        return key

    async def balance(self, db: AsyncSession, user_id: str) -> dict:
        """What the customer has left, split by pocket, read from OpenRouter."""
        row = await self._row(db, user_id)
        if not row.key_hash:
            return {
                "provisioned": False,
                "included_remaining_usd": 0.0,
                "purchased_remaining_usd": 0.0,
                "total_remaining_usd": 0.0,
            }

        remote = await self._call("GET", f"/{row.key_hash}")
        usage = _q(remote.get("usage") or 0)
        spent = max(Decimal(0), usage - _q(row.usage_at_period_start))
        from_included, from_purchased = self._split(spent, _q(row.included_grant_usd))
        included_left = max(Decimal(0), _q(row.included_grant_usd) - from_included)
        purchased_left = max(Decimal(0), _q(row.purchased_balance_usd) - from_purchased)
        return {
            "provisioned": True,
            "spent_this_period_usd": float(spent),
            "included_remaining_usd": float(included_left),
            "purchased_remaining_usd": float(purchased_left),
            "total_remaining_usd": float(included_left + purchased_left),
        }

    async def top_up(self, db: AsyncSession, user_id: str, *, amount_usd: float) -> dict:
        """Add purchased credit. Called from the webhook, once per Stripe event.

        Idempotency is the caller's: `handle_event` claims the event id before this runs,
        so a redelivery never reaches here. Adding it here as well would be a second
        ledger to keep in step with the first.
        """
        if amount_usd <= 0:
            raise CreditError("top-up amount must be positive")
        row = await self._row(db, user_id)
        if not row.key_hash:
            raise CreditError("cannot top up before the key is provisioned")

        remote = await self._call("GET", f"/{row.key_hash}")
        usage = _q(remote.get("usage") or 0)
        row.purchased_balance_usd = _q(_q(row.purchased_balance_usd) + _q(amount_usd))
        new_limit = await self._limit_for(row, usage)
        await self._call("PATCH", f"/{row.key_hash}", limit=float(new_limit))
        await db.commit()
        logger.info(
            "credit: topped up user=%s by %.2f; ceiling now %.2f",
            user_id[:8],
            amount_usd,
            float(new_limit),
        )
        return {
            "purchased_balance_usd": float(row.purchased_balance_usd),
            "limit_usd": float(new_limit),
        }

    async def renew(self, db: AsyncSession, user_id: str, *, included_usd: float) -> dict:
        """Roll the period: the included pocket is replaced, the purchased one carries.

        The order here is the whole of the expiry decision. Purchased credit is reduced
        only by what the included allowance could not cover, so an unused allowance costs
        the customer nothing and an over-run bills against what they bought.
        """
        row = await self._row(db, user_id)
        if not row.key_hash:
            return await self._noop_renew(row, included_usd)

        remote = await self._call("GET", f"/{row.key_hash}")
        usage = _q(remote.get("usage") or 0)
        spent = max(Decimal(0), usage - _q(row.usage_at_period_start))
        _, from_purchased = self._split(spent, _q(row.included_grant_usd))

        row.purchased_balance_usd = max(Decimal(0), _q(row.purchased_balance_usd) - from_purchased)
        row.included_grant_usd = _q(included_usd)
        row.usage_at_period_start = usage
        new_limit = await self._limit_for(row, usage)
        await self._call("PATCH", f"/{row.key_hash}", limit=float(new_limit))
        await db.commit()
        logger.info(
            "credit: renewed user=%s — included %.2f, purchased %.2f, ceiling %.2f",
            user_id[:8],
            included_usd,
            float(row.purchased_balance_usd),
            float(new_limit),
        )
        return {
            "included_grant_usd": float(row.included_grant_usd),
            "purchased_balance_usd": float(row.purchased_balance_usd),
            "limit_usd": float(new_limit),
        }

    async def _noop_renew(self, row: LlmCredit, included_usd: float) -> dict:
        """Renewal before a key exists: record the grant so `provision` starts from it."""
        row.included_grant_usd = _q(included_usd)
        return {
            "included_grant_usd": float(row.included_grant_usd),
            "purchased_balance_usd": float(row.purchased_balance_usd),
            "limit_usd": None,
        }

    async def revoke(self, db: AsyncSession, user_id: str) -> bool:
        """Delete the key on cancellation. The row stays: purchased credit is still owed."""
        row = await self._row(db, user_id)
        if not row.key_hash:
            return False
        await self._call("DELETE", f"/{row.key_hash}")
        row.key_hash = None
        row.key_encrypted = None
        row.included_grant_usd = _q(0)
        await db.commit()
        logger.info("credit: revoked key for user=%s", user_id[:8])
        return True
