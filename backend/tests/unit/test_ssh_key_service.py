from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

import app.models.chat_session  # noqa: F401 - ensure all models resolved
import app.models.connection  # noqa: F401
import app.models.project  # noqa: F401
import app.models.ssh_key  # noqa: F401
from app.services.ssh_key_service import SshKeyInUseError, SshKeyService

_test_key = asyncssh.generate_private_key("ssh-ed25519")
VALID_ED25519_KEY = _test_key.export_private_key("openssh").decode()


class TestSshKeyServiceValidation:
    def test_validate_valid_key(self):
        svc = SshKeyService()
        key_type, fingerprint = svc._validate_and_extract(VALID_ED25519_KEY, None)
        assert "ed25519" in key_type.lower() or "ssh-ed25519" in key_type.lower()
        assert len(fingerprint) > 0

    def test_validate_invalid_key(self):
        svc = SshKeyService()
        with pytest.raises(ValueError, match="Invalid SSH key"):
            svc._validate_and_extract("not a valid key", None)

    def test_validate_wrong_passphrase_on_encrypted_key(self):
        encrypted_key = _test_key.export_private_key("openssh", passphrase="correct").decode()
        svc = SshKeyService()
        with pytest.raises(ValueError):
            svc._validate_and_extract(encrypted_key, "wrong-passphrase")


class TestSshKeyServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_and_list(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await svc.create(mock_session, "test-key", VALID_ED25519_KEY)
        assert result.name == "test-key"
        assert result.fingerprint
        assert "ed25519" in result.key_type.lower() or "ssh-ed25519" in result.key_type.lower()
        assert result.private_key_encrypted  # encrypted, not plaintext
        assert result.private_key_encrypted != VALID_ED25519_KEY
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_passphrase(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await svc.create(mock_session, "pass-key", VALID_ED25519_KEY, passphrase=None)
        assert result.name == "pass-key"
        assert result.passphrase_encrypted is None

    @pytest.mark.asyncio
    async def test_get_decrypted(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        from app.services.encryption import encrypt

        mock_key.private_key_encrypted = encrypt(VALID_ED25519_KEY)
        mock_key.passphrase_encrypted = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_decrypted(mock_session, "key-123")
        assert result is not None
        key_content, passphrase = result
        assert key_content == VALID_ED25519_KEY.strip()
        assert passphrase is None

    @pytest.mark.asyncio
    async def test_get_decrypted_not_found(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_decrypted(mock_session, "nonexistent")
        assert result is None


class TestSshKeyServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_free_key(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        mock_key.name = "free-key"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch.object(svc, "_find_references", new_callable=AsyncMock, return_value=[]):
            deleted = await svc.delete(mock_session, "key-123")
        assert deleted is True
        mock_session.delete.assert_called_once_with(mock_key)

    @pytest.mark.asyncio
    async def test_delete_in_use_key(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        mock_key.name = "used-key"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(
            svc, "_find_references", new_callable=AsyncMock, return_value=["project:MyProject"]
        ):
            with pytest.raises(SshKeyInUseError) as exc_info:
                await svc.delete(mock_session, "key-123")
            assert "project:MyProject" in exc_info.value.references

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        deleted = await svc.delete(mock_session, "nonexistent")
        assert deleted is False
