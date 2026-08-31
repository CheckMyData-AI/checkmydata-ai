"""The entitlement question, asked by the product and answered by whoever is installed.

Four call sites ask it — `connections.py`, `projects.py`, `membership_service.py`,
`demo.py` — and they ask two things: may I create another project, may I create another
connection. `usage_service` asks a third: what is the token ceiling. That is the entire
surface, which is why the commercial layer can be lifted out along this line rather than
carved out of the product.

A ``Protocol``, not a base class, and structural on purpose: the private cloud package
must be able to satisfy it without importing from this repository. A dependency pointing
that way would make the split cosmetic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


class QuotaExceededError(Exception):
    """A plan quota (connections / projects) was reached (T-BILL-2 paywall).

    Moved here verbatim from `entitlement_service` rather than redesigned. The first
    version of this file invented a narrower signature — one `upgrade_hint` string — and
    mypy caught four call sites passing `resource`, `limit` and `current`. Inventing a
    shape for an exception that already had one is how a refactor loses the payload the
    frontend renders.
    """

    def __init__(self, message: str, *, resource: str, limit: int, current: int):
        super().__init__(message)
        self.resource = resource
        self.limit = limit
        self.current = current

    def as_payload(self) -> dict:
        return {
            "error": "plan_limit_reached",
            "resource": self.resource,
            "limit": self.limit,
            "current": self.current,
            "message": str(self),
            "upgrade_url": "/pricing",
        }


@runtime_checkable
class Entitlements(Protocol):
    """What the product may do, according to whoever is answering."""

    async def enforce_project_quota(self, db: AsyncSession, user_id: str) -> None:
        """Raise :class:`QuotaExceededError` if another project may not be created."""
        ...

    async def enforce_connection_quota(self, db: AsyncSession, user_id: str) -> None:
        """Raise :class:`QuotaExceededError` if another connection may not be created."""
        ...

    async def effective_token_limits(self, db: AsyncSession, user_id: str) -> tuple[int, int]:
        """``(daily, monthly)`` token ceilings. ``0`` means unlimited, matching the
        convention `check_budget` and `_strictest` already use — a second way to say the
        same thing is a second thing to keep in step."""
        ...
