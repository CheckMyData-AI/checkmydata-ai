"""Symmetric encryption for credentials at rest, with key rotation (F-CONN-05).

There used to be one key and no way off it. A leaked ``MASTER_ENCRYPTION_KEY``
could only be replaced by re-encrypting every stored secret by hand, and swapping
it outright makes every credential permanently unreadable — so in practice the key
was never rotated.

The shape now: ``MASTER_ENCRYPTION_KEY`` is the **only** key new ciphertext is
written with, and ``MASTER_ENCRYPTION_KEYS_OLD`` is a comma-separated list of
retired keys kept **for reading**. Rotation is therefore a two-step the operator
cannot get half-right: put the new key in ``MASTER_ENCRYPTION_KEY``, move the
previous one into ``MASTER_ENCRYPTION_KEYS_OLD``, deploy. Nothing is unreadable at
any point, and `app.ops.credential_rotation` sweeps the stored rows onto the new
key so the old one can eventually be dropped.

Two keys are deliberately kept in separate variables rather than one ordered list:
the primary is the one thing that must never be ambiguous, and a stray comma in a
single list would silently change which key writes.
"""

import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings

logger = logging.getLogger(__name__)

_primary: Fernet | None = None
_reader: MultiFernet | None = None
_loaded_from: tuple[str, str] | None = None


def _missing_primary() -> RuntimeError:
    return RuntimeError(
        "MASTER_ENCRYPTION_KEY is not set. Generate one with:\n"
        '  python -c "from cryptography.fernet import Fernet;'
        ' print(Fernet.generate_key().decode())"'
    )


def _build() -> tuple[Fernet, MultiFernet]:
    key = settings.master_encryption_key
    if not key:
        raise _missing_primary()
    primary = Fernet(key.encode() if isinstance(key, str) else key)

    old_raw = getattr(settings, "master_encryption_keys_old", "") or ""
    retired: list[Fernet] = []
    for idx, part in enumerate(old_raw.split(",")):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            retired.append(Fernet(candidate.encode()))
        except Exception as exc:
            # Refused loudly on purpose. A mistyped retired key that silently does
            # nothing is how a rotation "succeeds" while leaving rows nobody can
            # read — and the failure would surface later, on an unrelated request.
            raise RuntimeError(
                f"MASTER_ENCRYPTION_KEYS_OLD entry #{idx + 1} is not a valid Fernet "
                "key. Each entry must be a urlsafe-base64 32-byte key, as produced "
                'by: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc

    if retired:
        logger.info(
            "Encryption: 1 primary key + %d retired key(s) accepted for reading.",
            len(retired),
        )
    return primary, MultiFernet([primary, *retired])


def _get() -> tuple[Fernet, MultiFernet]:
    global _primary, _reader, _loaded_from
    stamp = (
        settings.master_encryption_key or "",
        getattr(settings, "master_encryption_keys_old", "") or "",
    )
    if _primary is None or _reader is None or _loaded_from != stamp:
        _primary, _reader = _build()
        _loaded_from = stamp
    return _primary, _reader


def reset_cache() -> None:
    """Drop the cached keys. For tests and for a deliberate in-process reload."""
    global _primary, _reader, _loaded_from
    _primary = _reader = _loaded_from = None


def encrypt(plaintext: str) -> str:
    """Encrypt with the primary key only — retired keys never write."""
    primary, _ = _get()
    return primary.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt with the primary key, falling back to each retired key in order."""
    _, reader = _get()
    try:
        return reader.decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.error("Decryption failed", exc_info=True)
        raise


def is_on_primary_key(ciphertext: str) -> bool:
    """True when this token was written with the current primary key.

    This is what answers the only question that matters during a rotation: *can the
    old key be dropped yet?* Fernet tokens carry no key id, so the test is whether
    the primary alone can read it.
    """
    primary, _ = _get()
    try:
        primary.decrypt(ciphertext.encode())
        return True
    except InvalidToken:
        return False


def rotate_token(ciphertext: str) -> str:
    """Re-encrypt a token under the primary key without changing what it means."""
    _, reader = _get()
    return reader.rotate(ciphertext.encode()).decode()


def key_fingerprint() -> str:
    """A stable, non-reversible id for the primary key.

    Used as the deploy marker that detects a rotation. It is a hash **of the key**,
    never the key: this value is written to the database and appears in logs.
    """
    key = settings.master_encryption_key
    if not key:
        raise _missing_primary()
    raw = key.encode() if isinstance(key, str) else key
    return hashlib.sha256(raw).hexdigest()[:16]
