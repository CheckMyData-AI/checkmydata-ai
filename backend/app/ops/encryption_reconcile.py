"""Detect an encryption-key rotation at boot and sweep the stored secrets (F-CONN-05).

Mirrors ``app.ops.embedding_reconcile`` deliberately, including the transaction-scoped
advisory lock that serialises concurrent dynos and the rule that the marker advances
**only after** the work succeeds, so a failure retries on the next boot.

The point is that rotation costs the operator two config values and a deploy. Without
this, retiring the old key would need a manual script nobody runs, which is how a
rotation ends up half-done and the old key is kept forever.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.base import async_session_factory
from app.models.deploy_state import DeployState
from app.ops.credential_rotation import rotate_credentials
from app.services.encryption import key_fingerprint

logger = logging.getLogger(__name__)

_FINGERPRINT_KEY = "encryption_key_fingerprint"
# Stable, arbitrary 64-bit key for pg_try_advisory_xact_lock — never change it.
_ADVISORY_LOCK_KEY = 0x43C0_0505_C0DE_0001


@dataclass
class EncryptionReconcileResult:
    status: str
    rotated: int = 0
    failed: int = 0
    fingerprint: str = ""


async def reconcile_encryption_keys(
    session_factory: async_sessionmaker | None = None,
) -> EncryptionReconcileResult:
    """Sweep credentials onto the primary key when that key has changed.

    Best-effort: never raises, never blocks boot. ``seeded`` on a database that has
    not seen this marker before — the existing rows are already on the only key there
    has ever been, so there is nothing to move.
    """
    try:
        current = key_fingerprint()
    except Exception:
        logger.warning("reconcile_encryption_keys: no primary key configured", exc_info=True)
        return EncryptionReconcileResult("error")

    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            if session.get_bind().dialect.name == "postgresql":
                locked = await session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                if not locked:
                    return EncryptionReconcileResult("skipped_locked", fingerprint=current)

            stored = await session.get(DeployState, _FINGERPRINT_KEY)
            if stored is None:
                session.add(DeployState(key=_FINGERPRINT_KEY, value=current))
                await session.commit()
                return EncryptionReconcileResult("seeded", fingerprint=current)
            if stored.value == current:
                return EncryptionReconcileResult("unchanged", fingerprint=current)
            previous = stored.value

        # Outside the marker session on purpose: the sweep opens its own short
        # transactions per batch, and holding the advisory lock across all of them
        # would block the other dyno for the whole run rather than for the check.
        result = await rotate_credentials(session_factory=factory)

        if result.failed:
            # The marker is NOT advanced. Some row is readable by no configured key,
            # so the retired key must stay — and saying the rotation is complete
            # while that is true is the lie this whole module exists to avoid.
            logger.error(
                "Encryption key changed (%s -> %s) but %d secret(s) are readable by no "
                "configured key: %s. KEEP the retired key in MASTER_ENCRYPTION_KEYS_OLD; "
                "the sweep will retry on the next boot.",
                previous,
                current,
                result.failed,
                ", ".join(result.unreadable[:10]),
            )
            return EncryptionReconcileResult(
                "partial",
                rotated=result.rotated,
                failed=result.failed,
                fingerprint=current,
            )

        async with factory() as session:
            marker = await session.get(DeployState, _FINGERPRINT_KEY)
            if marker is None:
                session.add(DeployState(key=_FINGERPRINT_KEY, value=current))
            else:
                marker.value = current
            await session.commit()

        logger.info(
            "Encryption key changed (%s -> %s); re-encrypted %d secret(s). "
            "MASTER_ENCRYPTION_KEYS_OLD can now be cleared.",
            previous,
            current,
            result.rotated,
        )
        return EncryptionReconcileResult("rotated", rotated=result.rotated, fingerprint=current)
    except Exception:
        logger.warning("reconcile_encryption_keys failed; marker untouched", exc_info=True)
        return EncryptionReconcileResult("error", fingerprint=current)
