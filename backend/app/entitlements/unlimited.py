"""The answer when no commercial layer is installed: yes.

This is the open-source build's provider. A product that fails closed on a missing billing
package is a product nobody can clone and run, which would defeat the point of shipping it
open in the first place.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class UnlimitedEntitlements:
    """Every quota passes; every ceiling is ``0 = unlimited``."""

    async def enforce_project_quota(self, db: AsyncSession, user_id: str) -> None:
        return None

    async def enforce_connection_quota(self, db: AsyncSession, user_id: str) -> None:
        return None

    async def effective_token_limits(self, db: AsyncSession, user_id: str) -> tuple[int, int]:
        """``(0, 0)`` — 0 = unlimited, the convention used throughout this codebase."""
        return (0, 0)
