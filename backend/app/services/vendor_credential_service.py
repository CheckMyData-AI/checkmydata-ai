"""Owner-scoped store for external analytics vendor credentials (spec §1.1).

Deliberately shaped like :mod:`app.services.ssh_key_service`: the plaintext goes
in as Fernet ciphertext and only ever comes back out through
:meth:`VendorCredentialService.get_decrypted`, which the collect path calls. No
response model in :mod:`app.api.routes.vendor_credentials` carries the secret or
its ciphertext; ``fingerprint`` (a sha256 prefix) answers "is this the same key?"
without handing anything back.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor_credential import VendorCredential
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

#: Providers this store accepts. ``appstore``/``googleplay`` are reserved for
#: modules m1/m2 — their secrets are opaque blobs (a ``.p8`` PEM, a service
#: account JSON) and are not parsed here.
SUPPORTED_PROVIDERS: tuple[str, ...] = ("ga4", "appstore", "googleplay")

#: Fields a Google service-account key must carry for GA4 auth to be possible.
_GA4_REQUIRED_FIELDS: tuple[str, ...] = ("client_email", "private_key")

#: Non-secret keys lifted out of a GA4 service-account JSON into ``meta_json``
#: so the UI can show *which* service account a credential is. Never widen this
#: to anything key-shaped.
_GA4_META_FIELDS: tuple[str, ...] = ("client_email", "project_id")


class InvalidVendorSecretError(ValueError):
    """The submitted provider/secret pair cannot be stored (→ HTTP 422).

    Raised *before* anything is persisted, so a rejected create leaves no row.
    """


class VendorCredentialInUseError(Exception):
    """A connection still references this credential (FK RESTRICT → HTTP 409)."""

    def __init__(self, credential_id: str) -> None:
        self.credential_id = credential_id
        super().__init__(f"Vendor credential {credential_id} is referenced by a connection")


def credential_meta(credential: VendorCredential) -> dict[str, Any] | None:
    """Decode ``meta_json`` defensively (a corrupt blob must not 500 a listing)."""
    if not credential.meta_json:
        return None
    try:
        parsed = json.loads(credential.meta_json)
    except json.JSONDecodeError:
        logger.warning("vendor_credential %s has unparseable meta_json", credential.id)
        return None
    return parsed if isinstance(parsed, dict) else None


class VendorCredentialService:
    @staticmethod
    def fingerprint(secret: str) -> str:
        """First 16 hex chars of sha256(plaintext) — an identity hint, not the key."""
        return hashlib.sha256(secret.encode()).hexdigest()[:16]

    def validate(self, provider: str, secret: str) -> dict[str, Any] | None:
        """Validate a provider/secret pair; return the non-secret meta to store.

        Raises :class:`InvalidVendorSecretError` with a message specific enough
        for a user to fix the paste on the first try.
        """
        if provider not in SUPPORTED_PROVIDERS:
            raise InvalidVendorSecretError(
                f"Unsupported provider '{provider}'. Expected one of: "
                f"{', '.join(SUPPORTED_PROVIDERS)}."
            )
        if not secret.strip():
            raise InvalidVendorSecretError("The credential secret is empty.")
        if provider != "ga4":
            # Reserved providers carry opaque key material (an App Store Connect
            # .p8 PEM, a Play service account) — m1/m2 add their own checks.
            return None

        try:
            parsed = json.loads(secret)
        except json.JSONDecodeError as exc:
            raise InvalidVendorSecretError(
                "A GA4 credential must be a Google service-account key file in "
                f"valid JSON — it did not parse: {exc.msg} (line {exc.lineno}, "
                f"column {exc.colno})."
            ) from exc

        if not isinstance(parsed, dict):
            raise InvalidVendorSecretError(
                "A GA4 credential must be a JSON object (the downloaded "
                f"service-account key file), not a {type(parsed).__name__}."
            )

        missing = [field for field in _GA4_REQUIRED_FIELDS if not parsed.get(field)]
        if missing:
            raise InvalidVendorSecretError(
                "The GA4 service-account JSON is missing required field(s): "
                f"{', '.join(missing)}. Download the key file from Google Cloud "
                "IAM → Service Accounts → Keys and paste it unmodified."
            )

        return {
            field: parsed[field] for field in _GA4_META_FIELDS if isinstance(parsed.get(field), str)
        }

    async def create(
        self,
        session: AsyncSession,
        name: str,
        provider: str,
        secret: str,
        user_id: str | None = None,
    ) -> VendorCredential:
        """Validate, encrypt and store one credential. Never logs the secret.

        The secret is stored **verbatim** — no stripping. A ``.p8`` PEM's
        trailing newline is part of the key material for some vendor parsers, so
        what comes back out of :meth:`get_decrypted` is byte-identical to what
        the user pasted.
        """
        meta = self.validate(provider, secret)

        credential = VendorCredential(
            user_id=user_id,
            name=name,
            provider=provider,
            secret_encrypted=encrypt(secret),
            fingerprint=self.fingerprint(secret),
            meta_json=json.dumps(meta) if meta else None,
        )
        session.add(credential)
        await session.commit()
        await session.refresh(credential)
        logger.info(
            "Created vendor credential '%s' (provider=%s, fingerprint=%s)",
            name,
            provider,
            credential.fingerprint,
        )
        return credential

    async def list_all(
        self, session: AsyncSession, user_id: str | None = None
    ) -> list[VendorCredential]:
        stmt = select(VendorCredential)
        if user_id:
            # R3 tenant isolation, same rule as ssh_key_service (F-SSH-06):
            # strictly owner-scoped. A NULL-owner credential must NOT leak to a
            # tenant, so do not union `VendorCredential.user_id.is_(None)` here —
            # that would show one user's vendor key to every other user. When
            # user_id is None the caller is trusted/internal (the collect job
            # resolving the credential already linked to a connection) and we
            # intentionally return everything.
            stmt = stmt.where(VendorCredential.user_id == user_id)
        result = await session.execute(stmt.order_by(VendorCredential.created_at.desc()))
        return list(result.scalars().all())

    async def get(
        self,
        session: AsyncSession,
        credential_id: str,
        user_id: str | None = None,
    ) -> VendorCredential | None:
        stmt = select(VendorCredential).where(VendorCredential.id == credential_id)
        if user_id:
            # R3 / F-SSH-06: strictly owner-scoped — never union NULL-owner rows
            # into a tenant's lookup. user_id=None is a trusted internal
            # lookup-by-id (collect job / worker) and stays unfiltered.
            stmt = stmt.where(VendorCredential.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_decrypted(
        self,
        session: AsyncSession,
        credential_id: str,
        user_id: str | None = None,
    ) -> str | None:
        """Return the plaintext secret, or None when the credential is not visible.

        Ownership is enforced through :meth:`get`, so a tenant can never decrypt
        another tenant's (or an unowned) credential.
        """
        credential = await self.get(session, credential_id, user_id=user_id)
        if not credential:
            return None
        try:
            return decrypt(credential.secret_encrypted)
        except Exception as exc:
            logger.error("Failed to decrypt vendor credential '%s': %s", credential.name, exc)
            raise ValueError(
                f"Cannot decrypt vendor credential '{credential.name}'. "
                "The encryption key may have changed."
            ) from exc

    async def delete(
        self, session: AsyncSession, credential_id: str, user_id: str | None = None
    ) -> bool:
        """Delete one credential. Returns False when it is not visible to the caller.

        Raises :class:`VendorCredentialInUseError` when a connection still points
        at it. The check is the database's: the FK is ON DELETE RESTRICT, so we
        attempt the delete and translate the IntegrityError instead of running a
        pre-check that a concurrent connection-create could slip past.
        """
        credential = await self.get(session, credential_id, user_id=user_id)
        if not credential:
            return False

        name = credential.name
        await session.delete(credential)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            logger.info(
                "Refused to delete vendor credential '%s': still referenced by a connection",
                name,
            )
            raise VendorCredentialInUseError(credential_id) from exc

        logger.info("Deleted vendor credential '%s'", name)
        return True
