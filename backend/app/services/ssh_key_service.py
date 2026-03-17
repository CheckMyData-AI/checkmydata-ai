import hashlib
import logging

import asyncssh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.project import Project
from app.models.ssh_key import SshKey
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)


class SshKeyInUseError(Exception):
    def __init__(self, references: list[str]):
        self.references = references
        super().__init__(f"SSH key is in use by: {', '.join(references)}")


class SshKeyService:
    def _validate_and_extract(
        self, private_key_pem: str, passphrase: str | None
    ) -> tuple[str, str]:
        """Validate a private key and return (key_type, fingerprint).

        Raises ValueError on invalid key or wrong passphrase.
        """
        try:
            key = asyncssh.import_private_key(private_key_pem, passphrase)
        except asyncssh.KeyImportError as exc:
            raise ValueError(f"Invalid SSH key: {exc}") from exc
        except asyncssh.KeyEncryptionError as exc:
            raise ValueError(f"Wrong passphrase: {exc}") from exc

        key_type = key.get_algorithm()
        public_data = key.export_public_key("openssh")
        fingerprint = hashlib.sha256(public_data).hexdigest()
        return key_type, fingerprint

    async def create(
        self,
        session: AsyncSession,
        name: str,
        private_key_pem: str,
        passphrase: str | None = None,
        user_id: str | None = None,
    ) -> SshKey:
        private_key_pem = private_key_pem.strip()
        key_type, fingerprint = self._validate_and_extract(private_key_pem, passphrase)

        ssh_key = SshKey(
            name=name,
            user_id=user_id,
            private_key_encrypted=encrypt(private_key_pem),
            passphrase_encrypted=encrypt(passphrase) if passphrase else None,
            fingerprint=fingerprint,
            key_type=key_type,
        )
        session.add(ssh_key)
        await session.commit()
        await session.refresh(ssh_key)
        logger.info("Created SSH key '%s' (type=%s)", name, key_type)
        return ssh_key

    async def list_all(self, session: AsyncSession, user_id: str | None = None) -> list[SshKey]:
        stmt = select(SshKey)
        if user_id:
            stmt = stmt.where((SshKey.user_id == user_id) | (SshKey.user_id.is_(None)))
        result = await session.execute(stmt.order_by(SshKey.created_at.desc()))
        return list(result.scalars().all())

    async def get(
        self, session: AsyncSession, key_id: str, user_id: str | None = None,
    ) -> SshKey | None:
        stmt = select(SshKey).where(SshKey.id == key_id)
        if user_id:
            stmt = stmt.where((SshKey.user_id == user_id) | (SshKey.user_id.is_(None)))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_decrypted(
        self, session: AsyncSession, key_id: str
    ) -> tuple[str, str | None] | None:
        """Return (private_key_pem, passphrase) decrypted. Internal use only."""
        ssh_key = await self.get(session, key_id)
        if not ssh_key:
            return None
        try:
            private_key_pem = decrypt(ssh_key.private_key_encrypted).strip()
            passphrase = (
                decrypt(ssh_key.passphrase_encrypted)
                if ssh_key.passphrase_encrypted
                else None
            )
        except Exception as exc:
            logger.error("Failed to decrypt SSH key '%s': %s", ssh_key.name, exc)
            raise ValueError(
                f"Cannot decrypt SSH key '{ssh_key.name}'."
                " The encryption key may have changed."
            ) from exc
        return private_key_pem, passphrase

    async def delete(self, session: AsyncSession, key_id: str) -> bool:
        ssh_key = await self.get(session, key_id)
        if not ssh_key:
            return False

        references = await self._find_references(session, key_id)
        if references:
            raise SshKeyInUseError(references)

        await session.delete(ssh_key)
        await session.commit()
        logger.info("Deleted SSH key '%s'", ssh_key.name)
        return True

    async def _find_references(self, session: AsyncSession, key_id: str) -> list[str]:
        refs: list[str] = []
        proj_result = await session.execute(
            select(Project.name).where(Project.ssh_key_id == key_id)
        )
        for (name,) in proj_result:
            refs.append(f"project:{name}")

        conn_result = await session.execute(
            select(Connection.name).where(Connection.ssh_key_id == key_id)
        )
        for (name,) in conn_result:
            refs.append(f"connection:{name}")

        return refs
