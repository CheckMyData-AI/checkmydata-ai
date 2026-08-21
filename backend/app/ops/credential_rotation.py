"""Sweep stored secrets onto the current primary encryption key (F-CONN-05).

A rotation is not finished when the config changes — it is finished when the retired
key can be **dropped**, and that is a property of the rows. This module is what makes
that property reachable, and countable.

Two things it is deliberately careful about:

* **The column set is derived, not remembered.** ``ENCRYPTED_COLUMNS`` is asserted
  against every mapped column whose name ends in ``_encrypted``, so a column added
  later cannot be silently left un-rotated — which would mean keeping the old key
  forever while the config claimed the rotation was done.
* **It never reports work it did not do.** A row whose ciphertext no key can read is
  counted as ``failed`` and named in the log, not skipped quietly: that row is the
  one thing standing between the operator and dropping the old key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import async_session_factory
from app.models.connection import Connection
from app.models.repository import ProjectRepository
from app.models.ssh_key import SshKey
from app.models.vendor_credential import VendorCredential
from app.services.encryption import is_on_primary_key, rotate_token

logger = logging.getLogger(__name__)

#: (model, encrypted column names). Held to the full declared set by a test.
#: Typed ``Any`` for the model slot on purpose: ``Base`` does not declare ``id``, and
#: the sweep needs it for stable pagination. All four models here have one, and the
#: derived-coverage test is what actually constrains this list.
ENCRYPTED_COLUMNS: list[tuple[Any, tuple[str, ...]]] = [
    (
        Connection,
        ("db_password_encrypted", "connection_string_encrypted", "mcp_env_encrypted"),
    ),
    (SshKey, ("private_key_encrypted", "passphrase_encrypted")),
    # Currently dead: no caller passes it and nothing reads it (`RepositoryService.
    # create` accepts the parameter, the route never supplies it, and it is absent
    # from ALLOWED_UPDATE_FIELDS). Swept anyway — the derived-coverage test would
    # otherwise fail, and more to the point a future writer must not be able to break
    # rotation by populating a column the sweep does not know about. Tracked as
    # F-REPO-04.
    (ProjectRepository, ("auth_token_encrypted",)),
    (VendorCredential, ("secret_encrypted",)),
]

#: Rows fetched per model per pass. Bounded so a large tenant cannot build one
#: transaction big enough to matter.
_BATCH = 200


@dataclass
class RotationResult:
    examined: int = 0
    rotated: int = 0
    failed: int = 0
    unreadable: list[str] = field(default_factory=list)


async def pending_rotation_count(session: AsyncSession) -> int:
    """How many stored secrets are still on a retired key.

    This is the retirement gate: while it is non-zero, dropping the old key would
    make those rows unreadable. Zero is the operator's green light.
    """
    total = 0
    for model, columns in ENCRYPTED_COLUMNS:
        stmt = select(model).where(or_(*[getattr(model, c).is_not(None) for c in columns]))
        rows: list[Any] = list((await session.scalars(stmt)).all())
        for row in rows:
            for col in columns:
                value = getattr(row, col)
                if value and not is_on_primary_key(value):
                    total += 1
    return total


async def rotate_credentials(
    session_factory: async_sessionmaker | None = None,
) -> RotationResult:
    """Re-encrypt every stored secret that is not on the primary key.

    Idempotent: a row already on the primary key is examined and left untouched, so a
    second run is cheap and a partial run resumes correctly. Best-effort per row — one
    unreadable value must not abandon the rest, because the rest are what let the old
    key be dropped.
    """
    factory = session_factory or async_session_factory
    result = RotationResult()

    for model, columns in ENCRYPTED_COLUMNS:
        offset = 0
        while True:
            async with factory() as session:
                rows = list(
                    (
                        await session.scalars(
                            select(model)
                            .where(or_(*[getattr(model, c).is_not(None) for c in columns]))
                            .order_by(model.id)
                            .offset(offset)
                            .limit(_BATCH)
                        )
                    ).all()
                )
                if not rows:
                    break
                for row in rows:
                    for col in columns:
                        value = getattr(row, col)
                        if not value:
                            continue
                        result.examined += 1
                        if is_on_primary_key(value):
                            continue
                        try:
                            setattr(row, col, rotate_token(value))
                            result.rotated += 1
                        except Exception:
                            result.failed += 1
                            result.unreadable.append(f"{model.__name__}.{col}#{row.id}")
                            logger.error(
                                "credential_rotation: %s.%s on row %s is readable by no "
                                "configured key — the retired key cannot be dropped while "
                                "this row exists",
                                model.__name__,
                                col,
                                row.id,
                                exc_info=True,
                            )
                await session.commit()
                offset += len(rows)

    if result.rotated or result.failed:
        logger.info(
            "credential_rotation: examined=%d rotated=%d failed=%d",
            result.examined,
            result.rotated,
            result.failed,
        )
    return result


async def count_all_encrypted(session: AsyncSession) -> int:
    """Total non-NULL encrypted values, for reporting alongside the pending count."""
    total = 0
    for model, columns in ENCRYPTED_COLUMNS:
        for col in columns:
            total += int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(model)
                        .where(getattr(model, col).is_not(None))
                    )
                ).scalar_one()
            )
    return total
